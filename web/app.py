"""
Interface web FastAPI v4 — catalogue hardcodé + gestion modèles + config
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

app = FastAPI(title="Local AI System", version="4.0")
orchestrator = Orchestrator(WORKSPACE)
ollama = OllamaClient()

# ── Catalogue hardcodé ────────────────────────────────────────────
HARDCODED_CATALOG = [
    # Code models
    {"name":"qwen2.5-coder:1.5b","params":"1.5B","size":"1.0 GB","vram":"2 GB","cat":"code","desc":"Ultra-léger, réponses rapides. Bon pour du scripting simple.","speed":"très rapide"},
    {"name":"qwen2.5-coder:3b","params":"3B","size":"1.9 GB","vram":"4 GB","cat":"code","desc":"Bon rapport qualité/vitesse pour du code courant.","speed":"rapide"},
    {"name":"qwen2.5-coder:7b","params":"7B","size":"4.7 GB","vram":"6 GB","cat":"code","desc":"Recommandé par défaut. Excellent en Python, JS, Rust, Go.","speed":"moyen","recommended":True},
    {"name":"qwen2.5-coder:14b","params":"14B","size":"9.0 GB","vram":"12 GB","cat":"code","desc":"Qualité supérieure. Gère des architectures complexes.","speed":"lent"},
    {"name":"qwen2.5-coder:32b","params":"32B","size":"20 GB","vram":"24 GB","cat":"code","desc":"Quasi GPT-4 en code. Nécessite un GPU puissant.","speed":"très lent"},
    {"name":"starcoder2:3b","params":"3B","size":"1.7 GB","vram":"4 GB","cat":"code","desc":"Spécialisé code multi-langage, léger.","speed":"rapide"},
    {"name":"starcoder2:7b","params":"7B","size":"4.0 GB","vram":"6 GB","cat":"code","desc":"Code multi-langage solide.","speed":"moyen"},
    {"name":"starcoder2:15b","params":"15B","size":"9.0 GB","vram":"12 GB","cat":"code","desc":"Très bon en complétion et génération de code.","speed":"lent"},
    {"name":"codellama:7b","params":"7B","size":"3.8 GB","vram":"6 GB","cat":"code","desc":"Meta, basé LLaMA. Bon en Python et infill.","speed":"moyen"},
    {"name":"codellama:13b","params":"13B","size":"7.4 GB","vram":"10 GB","cat":"code","desc":"Plus précis que le 7B, bon pour du code complexe.","speed":"lent"},
    {"name":"codellama:34b","params":"34B","size":"19 GB","vram":"24 GB","cat":"code","desc":"Le plus gros CodeLlama. Projets lourds.","speed":"très lent"},
    {"name":"yi-coder:1.5b","params":"1.5B","size":"0.9 GB","vram":"2 GB","cat":"code","desc":"Tiny mais étonnamment capable pour sa taille.","speed":"très rapide"},
    {"name":"yi-coder:9b","params":"9B","size":"5.0 GB","vram":"8 GB","cat":"code","desc":"Excellent rapport qualité/taille pour le code.","speed":"moyen"},
    {"name":"deepseek-coder-v2:16b","params":"16B","size":"8.9 GB","vram":"12 GB","cat":"code","desc":"MoE architecture, très bon en code structuré.","speed":"moyen"},
    # Reasoning models
    {"name":"deepseek-r1:1.5b","params":"1.5B","size":"1.1 GB","vram":"2 GB","cat":"reasoning","desc":"Raisonnement basique, ultra-rapide.","speed":"très rapide"},
    {"name":"deepseek-r1:7b","params":"7B","size":"4.7 GB","vram":"6 GB","cat":"reasoning","desc":"Bon raisonnement, idéal pour le planificateur.","speed":"moyen","recommended":True},
    {"name":"deepseek-r1:8b","params":"8B","size":"4.9 GB","vram":"6 GB","cat":"reasoning","desc":"Variante 8B, raisonnement chain-of-thought.","speed":"moyen"},
    {"name":"deepseek-r1:14b","params":"14B","size":"9.0 GB","vram":"12 GB","cat":"reasoning","desc":"Raisonnement avancé, décomposition de tâches complexes.","speed":"lent"},
    {"name":"deepseek-r1:32b","params":"32B","size":"20 GB","vram":"24 GB","cat":"reasoning","desc":"Raisonnement de niveau expert. GPU 24 Go requis.","speed":"très lent"},
    {"name":"deepseek-r1:70b","params":"70B","size":"43 GB","vram":"48 GB","cat":"reasoning","desc":"Le plus puissant. Multi-GPU ou quantifié.","speed":"extrême"},
    # General models
    {"name":"qwen3:0.6b","params":"0.6B","size":"0.5 GB","vram":"1 GB","cat":"general","desc":"Micro-modèle pour tests rapides.","speed":"instant"},
    {"name":"qwen3:1.7b","params":"1.7B","size":"1.2 GB","vram":"2 GB","cat":"general","desc":"Léger et polyvalent.","speed":"très rapide"},
    {"name":"qwen3:4b","params":"4B","size":"2.6 GB","vram":"4 GB","cat":"general","desc":"Bon équilibre général.","speed":"rapide"},
    {"name":"qwen3:8b","params":"8B","size":"5.2 GB","vram":"6 GB","cat":"general","desc":"Polyvalent et capable, bon pour review.","speed":"moyen"},
    {"name":"qwen3:14b","params":"14B","size":"9.2 GB","vram":"12 GB","cat":"general","desc":"Haute qualité générale.","speed":"lent"},
    {"name":"qwen3:30b","params":"30B","size":"19 GB","vram":"24 GB","cat":"general","desc":"Très performant en raisonnement et code.","speed":"très lent"},
    {"name":"qwen3:32b","params":"32B","size":"20 GB","vram":"24 GB","cat":"general","desc":"Le meilleur Qwen 3, quasi frontier.","speed":"très lent"},
    {"name":"llama3.3:70b","params":"70B","size":"43 GB","vram":"48 GB","cat":"general","desc":"Meta LLaMA 3.3, état de l'art open-source.","speed":"extrême"},
    {"name":"llama3.1:8b","params":"8B","size":"4.7 GB","vram":"6 GB","cat":"general","desc":"Bon généraliste Meta, fiable.","speed":"moyen"},
    {"name":"llama3.2:3b","params":"3B","size":"2.0 GB","vram":"4 GB","cat":"general","desc":"Compact Meta, bon pour review rapide.","speed":"rapide"},
    {"name":"gemma2:2b","params":"2B","size":"1.6 GB","vram":"3 GB","cat":"general","desc":"Google, petit mais efficace.","speed":"rapide"},
    {"name":"gemma2:9b","params":"9B","size":"5.5 GB","vram":"8 GB","cat":"general","desc":"Google, très bon généraliste.","speed":"moyen"},
    {"name":"gemma2:27b","params":"27B","size":"16 GB","vram":"20 GB","cat":"general","desc":"Google, haute qualité.","speed":"lent"},
    {"name":"mistral:7b","params":"7B","size":"4.1 GB","vram":"6 GB","cat":"general","desc":"Mistral AI, excellent rapport qualité/taille.","speed":"moyen"},
    {"name":"mixtral:8x7b","params":"47B MoE","size":"26 GB","vram":"32 GB","cat":"general","desc":"Mixture-of-Experts, très performant.","speed":"lent"},
    {"name":"phi4:14b","params":"14B","size":"9.1 GB","vram":"12 GB","cat":"general","desc":"Microsoft, raisonnement et code solides.","speed":"lent"},
    # Vision models
    {"name":"llava:7b","params":"7B","size":"4.5 GB","vram":"6 GB","cat":"vision","desc":"Vision + texte, analyse d'images.","speed":"moyen"},
    {"name":"llava:13b","params":"13B","size":"8.0 GB","vram":"10 GB","cat":"vision","desc":"Vision améliorée, descriptions précises.","speed":"lent"},
    # Embedding
    {"name":"nomic-embed-text","params":"137M","size":"0.3 GB","vram":"1 GB","cat":"embedding","desc":"Embeddings texte pour RAG/recherche.","speed":"instant"},
    {"name":"mxbai-embed-large","params":"335M","size":"0.7 GB","vram":"1 GB","cat":"embedding","desc":"Embeddings haute qualité.","speed":"instant"},
]

# ── Config ────────────────────────────────────────────────────────
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

active_model = {
    "planner":  runtime_config.get("models", {}).get("planner",  "qwen2.5-coder:7b"),
    "coder":    runtime_config.get("models", {}).get("coder",    "qwen2.5-coder:7b"),
    "reviewer": runtime_config.get("models", {}).get("reviewer", "qwen2.5-coder:7b"),
}

# ── WebSocket manager ─────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []
    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
    def disconnect(self, ws: WebSocket):
        if ws in self.active: self.active.remove(ws)
    async def broadcast(self, msg: dict):
        dead = []
        for ws in self.active:
            try: await ws.send_json(msg)
            except: dead.append(ws)
        for ws in dead: self.active.remove(ws)

manager = ConnectionManager()

# ── API Status ────────────────────────────────────────────────────
@app.get("/api/status")
async def status():
    alive = await ollama.is_alive()
    models = await ollama.list_models() if alive else []
    return {"ollama": alive, "models": models, "active_model": active_model,
            "workspace": str(WORKSPACE), "files": orchestrator.sandbox.list_files()}

# ── API Modèles ───────────────────────────────────────────────────
@app.get("/api/models/local")
async def local_models():
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            r.raise_for_status()
            data = r.json()
            models = []
            for m in data.get("models", []):
                size_bytes = m.get("size", 0)
                size_gb = f"{size_bytes / 1e9:.1f} GB" if size_bytes > 1e9 else f"{size_bytes / 1e6:.0f} MB"
                models.append({"name": m["name"], "size": size_gb,
                    "modified": m.get("modified_at", ""),
                    "family": m.get("details", {}).get("family", ""),
                    "params": m.get("details", {}).get("parameter_size", "")})
            return {"models": models, "count": len(models)}
    except Exception as e:
        return {"models": [], "count": 0, "error": str(e)}

@app.get("/api/models/catalog")
async def catalog_models():
    """Retourne le catalogue hardcodé + tente le live."""
    installed = []
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            if r.status_code == 200:
                installed = [m["name"] for m in r.json().get("models", [])]
    except: pass

    catalog = []
    for m in HARDCODED_CATALOG:
        entry = dict(m)
        entry["installed"] = any(
            i == entry["name"] or i.startswith(entry["name"].split(":")[0] + ":")
            for i in installed
        )
        catalog.append(entry)
    return {"models": catalog, "installed_names": installed}

@app.get("/api/models/search")
async def search_models(q: str = ""):
    """Search - returns hardcoded catalog filtered."""
    return await catalog_models()

@app.post("/api/models/set")
async def set_model(body: dict):
    model = body.get("model", "").strip()
    role = body.get("role", "all")
    if not model:
        return JSONResponse({"error": "model vide"}, status_code=400)
    from core.orchestrator import AGENTS
    if role in ("all", "coder"): active_model["coder"] = model; AGENTS["coder"] = model
    if role in ("all", "planner"): active_model["planner"] = model; AGENTS["planner"] = model
    if role in ("all", "reviewer"): active_model["reviewer"] = model; AGENTS["reviewer"] = model
    cfg = load_config(); cfg.setdefault("models", {})
    if role == "all":
        cfg["models"]["planner"] = cfg["models"]["coder"] = cfg["models"]["reviewer"] = model
    else:
        cfg["models"][role] = model
    save_config(cfg)
    return {"status": "ok", "active_model": active_model}

@app.post("/api/models/pull")
async def pull_model(body: dict):
    model = body.get("model", "").strip()
    if not model: return JSONResponse({"error": "model vide"}, status_code=400)
    asyncio.create_task(_pull_and_broadcast(model))
    return {"status": "pulling", "model": model}

@app.delete("/api/models/delete")
async def delete_model(body: dict):
    model = body.get("model", "").strip()
    if not model: return JSONResponse({"error": "model vide"}, status_code=400)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.request("DELETE", f"{OLLAMA_URL}/api/delete", json={"name": model})
            if r.status_code in (200, 204, 404):
                await manager.broadcast({"type": "model_deleted", "model": model})
                return {"status": "deleted", "model": model}
            return JSONResponse({"error": r.text}, status_code=r.status_code)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ── API Config ────────────────────────────────────────────────────
@app.get("/api/config")
async def get_config():
    return load_config()

@app.post("/api/config")
async def set_config(body: dict):
    try:
        cfg = load_config()
        def deep_merge(base, override):
            for k, v in override.items():
                if isinstance(v, dict) and isinstance(base.get(k), dict): deep_merge(base[k], v)
                else: base[k] = v
        deep_merge(cfg, body)
        save_config(cfg)
        _apply_config(cfg)
        return {"status": "ok", "config": cfg}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

def _apply_config(cfg: dict):
    from core.orchestrator import AGENTS
    import core.orchestrator as om
    agents_cfg = cfg.get("agents", {})
    if "max_retries" in agents_cfg: om.MAX_RETRIES = int(agents_cfg["max_retries"])
    models_cfg = cfg.get("models", {})
    for role in ("planner", "coder", "reviewer"):
        if role in models_cfg: AGENTS[role] = models_cfg[role]; active_model[role] = models_cfg[role]

# ── API Tâches ────────────────────────────────────────────────────
@app.post("/api/task")
async def run_task(body: dict):
    task = body.get("task", "").strip()
    if not task: return JSONResponse({"error": "task vide"}, status_code=400)
    asyncio.create_task(_run_and_broadcast(task))
    return {"status": "started", "task": task}

@app.get("/api/files")
async def list_files():
    return {"files": orchestrator.sandbox.list_files()}

@app.get("/api/file")
async def read_file(path: str):
    ok, content = orchestrator.sandbox.read_file(path)
    if not ok: return JSONResponse({"error": content}, status_code=404)
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
                if task: asyncio.create_task(_run_and_broadcast(task))
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
                        except: pass
        await manager.broadcast({"type": "pull_done", "model": model})
    except Exception as e:
        await manager.broadcast({"type": "pull_error", "model": model, "message": str(e)})
