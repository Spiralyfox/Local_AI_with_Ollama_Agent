"""
Point d'entrée principal — lance le serveur Uvicorn.
Usage: python main.py [--port 8080]
"""
import argparse
import sys
from pathlib import Path

# Patch pour servir index.html depuis web/
import uvicorn
from fastapi.responses import HTMLResponse

sys.path.insert(0, str(Path(__file__).parent))

from web.app import app


@app.get("/", response_class=HTMLResponse)
async def root():
    html = (Path(__file__).parent / "web" / "index.html").read_text()
    return HTMLResponse(html)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Local AI System")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    print(f"""
╔══════════════════════════════════════════╗
║        Local AI System — démarrage       ║
╠══════════════════════════════════════════╣
║  Interface : http://{args.host}:{args.port:<5}         ║
║  Workspace : ~/ai-workspace              ║
║  Backend   : Ollama (localhost:11434)    ║
╚══════════════════════════════════════════╝
""")
    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="warning",
    )
