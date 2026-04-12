#!/usr/bin/env bash
# start.sh — Lancer Local AI System
# Usage:
#   ./start.sh              → port 8080
#   ./start.sh 9090         → port 9090
#   ./start.sh --port 9090  → port 9090

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$DIR/.venv"

# ── Parse port ─────────────────────────────────────
PORT=8080
for arg in "$@"; do
  if [[ "$arg" =~ ^[0-9]+$ ]]; then PORT="$arg"
  elif [[ "$prev" == "--port" || "$prev" == "-p" ]]; then PORT="$arg"; fi
  prev="$arg"
done
# Handle --port=XXXX
for arg in "$@"; do
  if [[ "$arg" == --port=* ]]; then PORT="${arg#--port=}"; fi
done

# ── Check venv ─────────────────────────────────────
if [[ ! -d "$VENV" ]]; then
  echo "⚠  Environnement virtuel non trouvé."
  echo "   Lance d'abord :  ./scripts/install.sh"
  echo "   Ou manuellement :"
  echo "     python3 -m venv .venv"
  echo "     source .venv/bin/activate"
  echo "     pip install -r requirements.txt"
  exit 1
fi

# ── Check Ollama ───────────────────────────────────
if ! curl -sf http://localhost:11434/ &>/dev/null; then
  echo "⚠  Ollama ne répond pas sur localhost:11434"
  echo "   Lance :  ollama serve"
  echo "   (on continue quand même, tu pourras le lancer après)"
fi

# ── Start ──────────────────────────────────────────
source "$VENV/bin/activate"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║        Local AI System — démarrage       ║"
echo "╠══════════════════════════════════════════╣"
printf "║  Interface : http://127.0.0.1:%-11s║\n" "$PORT"
echo "║  Workspace : ~/ai-workspace              ║"
echo "║  Backend   : Ollama (localhost:11434)    ║"
echo "║  Arrêter   : Ctrl+C                     ║"
echo "╚══════════════════════════════════════════╝"
echo ""

exec python3 "$DIR/main.py" --port "$PORT"
