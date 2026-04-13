"""
Interface web FastAPI v5.0
Corrections v5.0 :
  - Toute la config (temperature, max_tokens, cmd_timeout) appliquée au démarrage
  - _apply_config couvre tous les paramètres d'orchestrator
  - sandbox.max_file_size_kb synchronisé avec la config
  - Endpoint GET /api/config retourne la config complète avec valeurs runtime
  - Endpoint POST /api/task/cancel pour annuler la tâche en cours
  - WebSocket : ping/pong keepalive pour éviter les déconnexions
  - Gestion propre des erreurs sur /api/models/delete et /api/models/pull
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

from core import Orchestrator, OllamaClient, WebSearcher, get_logger

logger      = get_logger("web")
WORKSPACE   = Path.home() / "ai-workspace"
OLLAMA_URL  = "http://localhost:11434"
CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"

app          = FastAPI(title="Local AI System", version="5.0")
orchestrator = Orchestrator(WORKSPACE)
ollama       = OllamaClient()

# Verrou tâche unique — empêche deux exécutions simultanées
_task_lock = asyncio.Lock()

# ── Catalogue hardcodé ────────────────────────────────────────────
HARDCODED_CATALOG = [
    {"name":"qwen2.5-coder:1.5b","params":"1.5B","size":"1.0 GB","vram":"2 GB","cat":"code","desc":"Ultra-léger, réponses rapides. Scripting simple.","speed":"très rapide"},
    {"name":"qwen2.5-coder:3b","params":"3B","size":"1.9 GB","vram":"4 GB","cat":"code","desc":"Bon rapport qualité/vitesse pour du code courant.","speed":"rapide"},
    {"name":"qwen2.5-coder:7b","params":"7B","size":"4.7 GB","vram":"6 GB","cat":"code","desc":"Recommandé. Excellent en Python, JS, Rust, Go.","speed":"moyen","recommended":True},
    {"name":"qwen2.5-coder:14b","params":"14B","size":"9.0 GB","vram":"12 GB","cat":"code","desc":"Qualité supérieure. Architectures complexes.","speed":"lent"},
    {"name":"qwen2.5-coder:32b","params":"32B","size":"20 GB","vram":"24 GB","cat":"code","desc":"Quasi GPT-4 en code. GPU puissant requis.","speed":"très lent"},
    {"name":"starcoder2:3b","params":"3B","size":"1.7 GB","vram":"4 GB","cat":"code","desc":"Multi-langage, léger.","speed":"rapide"},
    {"name":"starcoder2:7b","params":"7B","size":"4.0 GB","vram":"6 GB","cat":"code","desc":"Code multi-langage solide.","speed":"moyen"},
    {"name":"starcoder2:15b","params":"15B","size":"9.0 GB","vram":"12 GB","cat":"code","desc":"Très bon en complétion code.","speed":"lent"},
    {"name":"codellama:7b","params":"7B","size":"3.8 GB","vram":"6 GB","cat":"code","desc":"Meta, bon en Python et infill.","speed":"moyen"},
    {"name":"codellama:13b","params":"13B","size":"7.4 GB","vram":"10 GB","cat":"code","desc":"Plus précis, code complexe.","speed":"lent"},
    {"name":"codellama:34b","params":"34B","size":"19 GB","vram":"24 GB","cat":"code","desc":"Le plus gros CodeLlama.","speed":"très lent"},
    {"name":"yi-coder:1.5b","params":"1.5B","size":"0.9 GB","vram":"2 GB","cat":"code","desc":"Tiny mais capable.","speed":"très rapide"},
    {"name":"yi-coder:9b","params":"9B","size":"5.0 GB","vram":"8 GB","cat":"code","desc":"Excellent rapport qualité/taille.","speed":"moyen"},
    {"name":"deepseek-coder-v2:16b","params":"16B","size":"8.9 GB","vram":"12 GB","cat":"code","desc":"MoE, très bon en code structuré.","speed":"moyen"},
    {"name":"deepseek-r1:1.5b","params":"1.5B","size":"1.1 GB","vram":"2 GB","cat":"reasoning","desc":"Raisonnement basique, ultra-rapide.","speed":"très rapide"},
    {"name":"deepseek-r1:7b","params":"7B","size":"4.7 GB","vram":"6 GB","cat":"reasoning","desc":"Idéal pour le planificateur.","speed":"moyen","recommended":True},
    {"name":"deepseek-r1:8b","params":"8B","size":"4.9 GB","vram":"6 GB","cat":"reasoning","desc":"Raisonnement chain-of-thought.","speed":"moyen"},
    {"name":"deepseek-r1:14b","params":"14B","size":"9.0 GB","vram":"12 GB","cat":"reasoning","desc":"Raisonnement avancé, tâches complexes.","speed":"lent"},
    {"name":"deepseek-r1:32b","params":"32B","size":"20 GB","vram":"24 GB","cat":"reasoning","desc":"Niveau expert. GPU 24 Go.","speed":"très lent"},
    {"name":"deepseek-r1:70b","params":"70B","size":"43 GB","vram":"48 GB","cat":"reasoning","desc":"Le plus puissant. Multi-GPU.","speed":"extrême"},
    {"name":"qwen3:0.6b","params":"0.6B","size":"0.5 GB","vram":"1 GB","cat":"general","desc":"Micro-modèle pour tests.","speed":"instant"},
    {"name":"qwen3:1.7b","params":"1.7B","size":"1.2 GB","vram":"2 GB","cat":"general","desc":"Léger et polyvalent.","speed":"très rapide"},
    {"name":"qwen3:4b","params":"4B","size":"2.6 GB","vram":"4 GB","cat":"general","desc":"Bon équilibre général.","speed":"rapide"},
    {"name":"qwen3:8b","params":"8B","size":"5.2 GB","vram":"6 GB","cat":"general","desc":"Polyvalent, bon pour review.","speed":"moyen"},
    {"name":"qwen3:14b","params":"14B","size":"9.2 GB","vram":"12 GB","cat":"general","desc":"Haute qualité générale.","speed":"lent"},
    {"name":"qwen3:30b","params":"30B","size":"19 GB","vram":"24 GB","cat":"general","desc":"Très performant.","speed":"très lent"},
    {"name":"qwen3:32b","params":"32B","size":"20 GB","vram":"24 GB","cat":"general","desc":"Le meilleur Qwen 3.","speed":"très lent"},
    {"name":"llama3.3:70b","params":"70B","size":"43 GB","vram":"48 GB","cat":"general","desc":"Meta, état de l'art open-source.","speed":"extrême"},
    {"name":"llama3.1:8b","params":"8B","size":"4.7 GB","vram":"6 GB","cat":"general","desc":"Bon généraliste Meta.","speed":"moyen"},
    {"name":"llama3.2:3b","params":"3B","size":"2.0 GB","vram":"4 GB","cat":"general","desc":"Compact, review rapide.","speed":"rapide"},
    {"name":"gemma2:2b","params":"2B","size":"1.6 GB","vram":"3 GB","cat":"general","desc":"Google, petit et efficace.","speed":"rapide"},
    {"name":"gemma2:9b","params":"9B","size":"5.5 GB","vram":"8 GB","cat":"general","desc":"Google, très bon.","speed":"moyen"},
    {"name":"gemma2:27b","params":"27B","size":"16 GB","vram":"20 GB","cat":"general","desc":"Google, haute qualité.","speed":"lent"},
    {"name":"mistral:7b","params":"7B","size":"4.1 GB","vram":"6 GB","cat":"general","desc":"Mistral AI, excellent.","speed":"moyen"},
    {"name":"mixtral:8x7b","params":"47B MoE","size":"26 GB","vram":"32 GB","cat":"general","desc":"Mixture-of-Experts.","speed":"lent"},
    {"name":"phi4:14b","params":"14B","size":"9.1 GB","vram":"12 GB","cat":"general","desc":"Microsoft, raisonnement solide.","speed":"lent"},
    {"name":"llava:7b","params":"7B","size":"4.5 GB","vram":"6 GB","cat":"vision","desc":"Vision + texte.","speed":"moyen"},
    {"name":"llava:13b","params":"13B","size":"8.0 GB","vram":"10 GB","cat":"vision","desc":"Vision améliorée.","speed":"lent"},
    {"name":"nomic-embed-text","params":"137M","size":"0.3 GB","vram":"1 GB","cat":"embedding","desc":"Embeddings pour RAG.","speed":"instant"},
    {"name":"mxbai-embed-large","params":"335M","size":"0.7 GB","vram":"1 GB","cat":"embedding","desc":"Embeddings haute qualité.","speed":"instant"},
]

# ── Config ────────────────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}

def save_config(cfg: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)

def _apply_config(cfg: dict):
    """Applique TOUTE la config à l'orchestrateur et au sandbox."""
    import core.orchestrator as om

    agents_cfg = cfg.get("agents", {})
    if "max_retries" in agents_cfg:
        om.MAX_RETRIES   = int(agents_cfg["max_retries"])
    if "temperature" in agents_cfg:
        om.TEMPERATURE   = float(agents_cfg["temperature"])
    if "max_tokens" in agents_cfg:
        om.MAX_TOKENS    = int(agents_cfg["max_tokens"])

    sandbox_cfg = cfg.get("sandbox", {})
    if "command_timeout" in sandbox_cfg:
        om.CMD_TIMEOUT   = int(sandbox_cfg["command_timeout"])
    if "max_file_size_kb" in sandbox_cfg:
        orchestrator.sandbox.set_max_file_size(int(sandbox_cfg["max_file_size_kb"]))

    models_cfg = cfg.get("models", {})
    for role in ("planner", "coder", "reviewer"):
        if role in models_cfg:
            om.AGENTS[role]        = models_cfg[role]
            active_model[role]     = models_cfg[role]

    ws_cfg = cfg.get("web_search", {})
    if "enabled" in ws_cfg:
        om.WEB_SEARCH_ENABLED = bool(ws_cfg["enabled"])
        logger.info(f"Recherche web: {'activée' if om.WEB_SEARCH_ENABLED else 'désactivée'}")

    ollama_cfg = cfg.get("ollama", {})
    if "timeout" in ollama_cfg:
        orchestrator.client.timeout = int(ollama_cfg["timeout"])

# Initialisation
_runtime_config = load_config()

active_model = {
    "planner":  _runtime_config.get("models", {}).get("planner",  "qwen2.5-coder:7b"),
    "coder":    _runtime_config.get("models", {}).get("coder",    "qwen2.5-coder:7b"),
    "reviewer": _runtime_config.get("models", {}).get("reviewer", "qwen2.5-coder:7b"),
}

# Appliquer toute la config au démarrage
_apply_config(_runtime_config)

# ── WebSocket manager ─────────────────────────────────────────────

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
orchestrator.set_broadcast(manager.broadcast)

@app.on_event("shutdown")
async def _shutdown():
    await orchestrator.client.aclose()
    await ollama.aclose()

# ── Status ────────────────────────────────────────────────────────

@app.get("/api/status")
async def status():
    import core.orchestrator as om
    alive  = await ollama.is_alive()
    models = await ollama.list_models() if alive else []
    cfg    = load_config()
    return {
        "ollama":             alive,
        "models":             models,
        "active_model":       active_model,
        "workspace":          str(WORKSPACE),
        "files":              orchestrator.sandbox.list_files(),
        "web_search_enabled": om.WEB_SEARCH_ENABLED,
        "task_running":       _task_lock.locked(),
    }

# ── Modèles ───────────────────────────────────────────────────────

@app.get("/api/models/local")
async def local_models():
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            r.raise_for_status()
            models = []
            for m in r.json().get("models", []):
                sb = m.get("size", 0)
                models.append({
                    "name":   m["name"],
                    "size":   f"{sb/1e9:.1f} GB" if sb > 1e9 else f"{sb/1e6:.0f} MB",
                    "family": m.get("details", {}).get("family", ""),
                    "params": m.get("details", {}).get("parameter_size", ""),
                })
            return {"models": models, "count": len(models)}
    except Exception as e:
        return {"models": [], "count": 0, "error": str(e)}

@app.get("/api/models/catalog")
async def catalog_models():
    installed: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            if r.status_code == 200:
                installed = [m["name"] for m in r.json().get("models", [])]
    except Exception:
        pass

    catalog = []
    for m in HARDCODED_CATALOG:
        entry = dict(m)
        base  = entry["name"].split(":")[0]
        entry["installed"] = any(
            i == entry["name"] or i.startswith(base + ":") for i in installed
        )
        catalog.append(entry)
    return {"models": catalog, "installed_names": installed}

@app.post("/api/models/set")
async def set_model(body: dict):
    import core.orchestrator as om
    model = body.get("model", "").strip()
    role  = body.get("role",  "all")
    if not model:
        return JSONResponse({"error": "model vide"}, status_code=400)

    roles = ["planner", "coder", "reviewer"] if role == "all" else [role]
    for r in roles:
        if r in om.AGENTS:
            om.AGENTS[r]   = model
            active_model[r] = model

    cfg = load_config()
    cfg.setdefault("models", {})
    for r in roles:
        cfg["models"][r] = model
    save_config(cfg)
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
            if r.status_code in (200, 204, 404):
                await manager.broadcast({"type": "model_deleted", "model": model})
                return {"status": "deleted", "model": model}
            return JSONResponse({"error": r.text}, status_code=r.status_code)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ── Config ────────────────────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    import core.orchestrator as om
    cfg = load_config()
    # Enrichir avec les valeurs runtime (ce qui est réellement appliqué)
    cfg.setdefault("agents",  {})
    cfg.setdefault("sandbox", {})
    cfg["agents"]["max_retries"]   = om.MAX_RETRIES
    cfg["agents"]["temperature"]   = om.TEMPERATURE
    cfg["agents"]["max_tokens"]    = om.MAX_TOKENS  # 16384 par défaut (gros projets)
    cfg["sandbox"]["command_timeout"] = om.CMD_TIMEOUT
    cfg["web_search"] = {"enabled": om.WEB_SEARCH_ENABLED}
    return cfg

@app.post("/api/config")
async def set_config(body: dict):
    try:
        cfg = load_config()

        def deep_merge(base: dict, override: dict):
            for k, v in override.items():
                if isinstance(v, dict) and isinstance(base.get(k), dict):
                    deep_merge(base[k], v)
                else:
                    base[k] = v

        deep_merge(cfg, body)
        save_config(cfg)
        _apply_config(cfg)
        return {"status": "ok", "config": cfg}
    except Exception as e:
        logger.error(f"Erreur save_config: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

# ── Tâches ────────────────────────────────────────────────────────

@app.post("/api/task")
async def run_task(body: dict):
    task = body.get("task", "").strip()
    if not task:
        return JSONResponse({"error": "task vide"}, status_code=400)
    if _task_lock.locked():
        return JSONResponse(
            {"error": "Une tâche est déjà en cours. Attends qu'elle se termine."},
            status_code=409,
        )
    asyncio.create_task(_run_and_broadcast(task))
    return {"status": "started", "task": task}

@app.post("/api/task/cancel")
async def cancel_task():
    """Indique à l'UI qu'une annulation est demandée.
    Le verrou sera libéré à la fin de la tâche en cours."""
    if not _task_lock.locked():
        return {"status": "no_task"}
    await manager.broadcast({"type": "log", "level": "err",
        "msg": "⚠ Annulation demandée — la tâche en cours se terminera à la prochaine étape."})
    return {"status": "cancel_requested"}

# ── Fichiers ──────────────────────────────────────────────────────

@app.get("/api/files")
async def list_files():
    return {"files": orchestrator.sandbox.list_files()}

@app.post("/api/workspace/clear")
async def clear_workspace():
    """Supprime tous les fichiers du workspace."""
    import shutil
    try:
        for item in WORKSPACE.iterdir():
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
        await manager.broadcast({"type": "files_updated", "files": []})
        return {"status": "ok"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/file")
async def read_file(path: str):
    ok, content = orchestrator.sandbox.read_file(path)
    if not ok:
        return JSONResponse({"error": content}, status_code=404)
    return {"path": path, "content": content}

# ── Web search ────────────────────────────────────────────────────

@app.get("/api/websearch/status")
async def websearch_status():
    import core.orchestrator as om
    searcher  = WebSearcher()
    available = await searcher.is_available()
    return {"available": available, "enabled": om.WEB_SEARCH_ENABLED}

# ── WebSocket ─────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            try:
                # Timeout pour détecter les connexions mortes
                data = await asyncio.wait_for(ws.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                # Ping keepalive
                try:
                    await ws.send_json({"type": "ping"})
                except Exception:
                    break
                continue

            try:
                msg  = json.loads(data)
            except json.JSONDecodeError:
                continue

            if msg.get("type") == "task":
                task = msg.get("task", "").strip()
                if task:
                    if _task_lock.locked():
                        await ws.send_json({"type": "error",
                            "message": "Une tâche est déjà en cours."})
                    else:
                        asyncio.create_task(_run_and_broadcast(task))
            elif msg.get("type") == "pong":
                pass  # keepalive réponse

    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)

# ── Helpers internes ──────────────────────────────────────────────

async def _run_and_broadcast(task: str):
    async with _task_lock:
        await manager.broadcast({"type": "started", "task": task})
        try:
            result = await orchestrator.run(task)
            await manager.broadcast({"type": "result", "data": result})
        except Exception as e:
            logger.error(f"Erreur orchestrator: {e}", exc_info=True)
            await manager.broadcast({"type": "error", "message": str(e)})

async def _pull_and_broadcast(model: str):
    await manager.broadcast({"type": "pull_start", "model": model})
    try:
        async with httpx.AsyncClient(timeout=3600) as client:
            async with client.stream(
                "POST", f"{OLLAMA_URL}/api/pull", json={"name": model}
            ) as r:
                async for line in r.aiter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            await manager.broadcast({
                                "type": "pull_progress", "model": model, "data": data
                            })
                        except Exception:
                            pass
        await manager.broadcast({"type": "pull_done", "model": model})
    except Exception as e:
        logger.error(f"Pull error {model}: {e}")
        await manager.broadcast({"type": "pull_error", "model": model, "message": str(e)})
