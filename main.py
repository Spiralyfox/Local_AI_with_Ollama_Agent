#!/usr/bin/env python3
"""
Point d'entrée principal — lance le serveur Uvicorn.
Usage:
  python3 main.py                  → port 8080
  python3 main.py --port 9090     → port 9090
  python3 main.py --host 0.0.0.0  → accessible depuis le réseau local
"""
import argparse
import sys
from pathlib import Path

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
    parser.add_argument("--host", default="127.0.0.1",
                        help="Adresse d'écoute (défaut: 127.0.0.1, utilise 0.0.0.0 pour le réseau local)")
    parser.add_argument("--port", "-p", type=int, default=8080,
                        help="Port d'écoute (défaut: 8080)")
    parser.add_argument("--reload", action="store_true",
                        help="Hot-reload en développement")
    args = parser.parse_args()

    print(f"""
╔══════════════════════════════════════════╗
║        Local AI System — démarrage       ║
╠══════════════════════════════════════════╣
║  Interface : http://{args.host}:{args.port:<5}         ║
║  Workspace : ~/ai-workspace              ║
║  Backend   : Ollama (localhost:11434)    ║
║  Arrêter   : Ctrl+C                     ║
╚══════════════════════════════════════════╝
""")
    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="warning",
    )
