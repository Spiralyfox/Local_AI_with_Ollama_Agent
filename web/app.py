"""
Interface web FastAPI v3 — gestion modèles dynamique + configuration
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
import asyncio
import json
import httpx
from pathlib import Path
import sys
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import Orchestrator, OllamaClient, get_logger

logger = get_logger("web")

WORKSPACE = Path.home() / "ai-workspace"
OLLAMA_URL = "http://localhost:11434"
CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"

app = FastAPI(title="Local AI System", version="3.0")
orchestrator = Orchestrator(WORKSPACE)
ollama = OllamaClient()

# Config en mémoire (chargée depuis config.yaml)
def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}

def save_config(cfg: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)

runtime_config = load_config()

# Modèles actifs
active_model = {
    "planner":  runtime_config.get("models", {}).get("planner",  "qwen2.5-coder:7b"),
    "coder":    runtime_config.get("models", {}).get("coder",    "qwen2.5-coder:7b"),
    "reviewer": runtime_config.get("models", {}).get("reviewer", "qwen2.5-coder:7b"),
}

# WebSocket manager
class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, msg: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active.remove(ws)

manager = ConnectionManager()

# ── API Status ────────────────────────────────────────────────────

@app.get("/api/status")
async def status():
    alive = await ollama.is_alive()
    models = await ollama.list_models() if alive else []
    return {
        "ollama": alive,
        "models": models,
        "active_model": active_model,
        "workspace": str(WORKSPACE),
        "files": orchestrator.sandbox.list_files(),
    }

# ── API Modèles ───────────────────────────────────────────────────

@app.get("/api/models/local")
async def local_models():
    """Liste les modèles réellement installés via Ollama."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            r.raise_for_status()
            data = r.json()
            models = []
            for m in data.get("models", []):
                size_bytes = m.get("size", 0)
                size_gb = f"{size_bytes / 1e9:.1f} GB" if size_bytes > 1e9 else f"{size_bytes / 1e6:.0f} MB"
                models.append({
                    "name": m["name"],
                    "size": size_gb,
                    "modified": m.get("modified_at", ""),
                    "family": m.get("details", {}).get("family", ""),
                    "params": m.get("details", {}).get("parameter_size", ""),
                })
            return {"models": models, "count": len(models)}
    except Exception as e:
        return {"models": [], "count": 0, "error": str(e)}

@app.get("/api/models/search")
async def search_models(q: str = ""):
    """Recherche dans le registre Ollama en ligne."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            url = "https://ollama.com/api/models"
            params = {"q": q, "p": 1} if q else {"p": 1}
            r = await client.get(url, params=params)
            if r.status_code == 200:
                return r.json()
            return {"models": [], "error": f"HTTP {r.status_code}"}
    except Exception as e:
        # Fallback catalogue statique si pas de net
        return {"models": [], "error": str(e), "offline": True}

@app.post("/api/models/set")
async def set_model(body: dict):
    model = body.get("model", "").strip()
    role  = body.get("role", "all")
    if not model:
        return JSONResponse({"error": "model vide"}, status_code=400)

    from core.orchestrator import AGENTS
    if role == "all" or role == "coder":
        active_model["coder"] = model
        AGENTS["coder"] = model
    if role == "all" or role == "planner":
        active_model["planner"] = model
        AGENTS["planner"] = model
    if role == "all" or role == "reviewer":
        active_model["reviewer"] = model
        AGENTS["reviewer"] = model

    # Persister dans config.yaml
    cfg = load_config()
    cfg.setdefault("models", {})
    if role == "all":
        cfg["models"]["planner"] = cfg["models"]["coder"] = cfg["models"]["reviewer"] = model
    else:
        cfg["models"][role] = model
    save_config(cfg)

    logger.info(f"Modèle {role} → {model}")
    return {"status": "ok", "active_model": active_model}

@app.post("/api/models/pull")
async def pull_model(body: dict):
    model = body.get("model", "").strip()
    if not model:
        return JSONResponse({"error": "model vide"}, status_code=400)
    asyncio.create_task(_pull_and_broadcast(model))
    return {"status": "pulling", "model": model}

@app.delete("/api/models/delete")
async def delete_model(body: dict):
    model = body.get("model", "").strip()
    if not model:
        return JSONResponse({"error": "model vide"}, status_code=400)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.request("DELETE", f"{OLLAMA_URL}/api/delete", json={"name": model})
            # Ollama retourne 200 si supprimé, 404 si inexistant
            if r.status_code in (200, 204, 404):
                # Vérifier que c'est vraiment parti
                verify = await client.get(f"{OLLAMA_URL}/api/tags")
                installed = [m["name"] for m in verify.json().get("models", [])]
                if model in installed:
                    return JSONResponse({"error": "Suppression échouée, modèle encore présent"}, status_code=500)
                await manager.broadcast({"type": "model_deleted", "model": model})
                return {"status": "deleted", "model": model}
            return JSONResponse({"error": r.text}, status_code=r.status_code)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ── API Configuration ─────────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    return load_config()

@app.post("/api/config")
async def set_config(body: dict):
    try:
        cfg = load_config()
        # Merge profond
        def deep_merge(base, override):
            for k, v in override.items():
                if isinstance(v, dict) and isinstance(base.get(k), dict):
                    deep_merge(base[k], v)
                else:
                    base[k] = v
        deep_merge(cfg, body)
        save_config(cfg)
        # Appliquer les changements runtime
        _apply_config(cfg)
        return {"status": "ok", "config": cfg}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

def _apply_config(cfg: dict):
    """Applique la config sans redémarrer."""
    from core import orchestrator as orc_module
    from core.orchestrator import AGENTS
    agents_cfg = cfg.get("agents", {})
    if "max_retries" in agents_cfg:
        import core.orchestrator as om
        om.MAX_RETRIES = int(agents_cfg["max_retries"])
    if "temperature" in agents_cfg:
        import core.orchestrator as om
        # Propagé via OllamaClient au prochain appel
        pass
    models_cfg = cfg.get("models", {})
    for role in ("planner", "coder", "reviewer"):
        if role in models_cfg:
            AGENTS[role] = models_cfg[role]
            active_model[role] = models_cfg[role]

# ── API Tâches ────────────────────────────────────────────────────

@app.post("/api/task")
async def run_task(body: dict):
    task = body.get("task", "").strip()
    if not task:
        return JSONResponse({"error": "task vide"}, status_code=400)
    asyncio.create_task(_run_and_broadcast(task))
    return {"status": "started", "task": task}

@app.get("/api/files")
async def list_files():
    return {"files": orchestrator.sandbox.list_files()}

@app.get("/api/file")
async def read_file(path: str):
    ok, content = orchestrator.sandbox.read_file(path)
    if not ok:
        return JSONResponse({"error": content}, status_code=404)
    return {"path": path, "content": content}

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "task":
                task = msg.get("task", "").strip()
                if task:
                    asyncio.create_task(_run_and_broadcast(task))
    except WebSocketDisconnect:
        manager.disconnect(ws)

# ── Helpers ───────────────────────────────────────────────────────

async def _run_and_broadcast(task: str):
    await manager.broadcast({"type": "started", "task": task})
    try:
        result = await orchestrator.run(task)
        await manager.broadcast({"type": "result", "data": result})
    except Exception as e:
        await manager.broadcast({"type": "error", "message": str(e)})

async def _pull_and_broadcast(model: str):
    await manager.broadcast({"type": "pull_start", "model": model})
    try:
        async with httpx.AsyncClient(timeout=3600) as client:
            async with client.stream("POST", f"{OLLAMA_URL}/api/pull", json={"name": model}) as r:
                async for line in r.aiter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            await manager.broadcast({"type": "pull_progress", "model": model, "data": data})
                        except Exception:
                            pass
        await manager.broadcast({"type": "pull_done", "model": model})
    except Exception as e:
        await manager.broadcast({"type": "pull_error", "model": model, "message": str(e)})
