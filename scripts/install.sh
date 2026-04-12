#!/usr/bin/env bash
# install.sh — Installation complète de Local AI System
# Idempotent : peut être relancé sans casser l'existant
set -euo pipefail

GREEN="\033[92m"; AMBER="\033[93m"; RED="\033[91m"; RESET="\033[0m"; BOLD="\033[1m"
info()  { echo -e "${GREEN}[✔]${RESET} $*"; }
warn()  { echo -e "${AMBER}[!]${RESET} $*"; }
error() { echo -e "${RED}[✘]${RESET} $*"; exit 1; }
step()  { echo -e "\n${BOLD}── $* ──${RESET}"; }

# Répertoire racine du projet (parent de scripts/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

step "Vérifications"
[[ "$(id -u)" -eq 0 ]] && error "Ne pas lancer en root !"

# Trouver python3
if ! command -v python3 &>/dev/null; then
  error "python3 introuvable. Installe-le avec : sudo apt install python3 python3-venv"
fi
python_version=$(python3 --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
major=$(echo "$python_version" | cut -d. -f1)
minor=$(echo "$python_version" | cut -d. -f2)
[[ "$major" -ge 3 && "$minor" -ge 10 ]] || error "Python 3.10+ requis (actuel: $python_version)"
info "Python $python_version"

[[ -f "$SCRIPT_DIR/requirements.txt" ]] || error "requirements.txt introuvable dans $SCRIPT_DIR"
info "Projet trouvé : $SCRIPT_DIR"

step "Installation Ollama"
if ! command -v ollama &>/dev/null; then
  warn "Ollama non trouvé — installation..."
  curl -fsSL https://ollama.com/install.sh | sh
  info "Ollama installé"
else
  info "Ollama déjà présent : $(ollama --version 2>&1 || echo '?')"
fi

if ! curl -sf http://localhost:11434/ &>/dev/null; then
  warn "Démarrage d'Ollama en background..."
  nohup ollama serve &>/tmp/ollama.log &
  sleep 3
fi

step "Téléchargement du modèle par défaut"
pull_model() {
  local model="$1"
  if ollama list 2>/dev/null | grep -q "^${model}"; then
    info "Modèle déjà présent : $model"
  else
    info "Téléchargement : $model (~4 Go)..."
    ollama pull "$model"
  fi
}
pull_model "qwen2.5-coder:7b"

echo ""
warn "DeepSeek R1 (raisonnement, 4.7 GB) est optionnel. Installer ? [o/N]"
read -r ans
if [[ "$ans" =~ ^[oO]$ ]]; then pull_model "deepseek-r1:7b"; fi

step "Environnement Python"
VENV="$SCRIPT_DIR/.venv"
if [[ ! -d "$VENV" ]]; then
  python3 -m venv "$VENV"
  info "Virtualenv créé : $VENV"
else
  info "Virtualenv existant : $VENV"
fi
source "$VENV/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -r "$SCRIPT_DIR/requirements.txt"
info "Dépendances Python installées"

step "Workspace sandbox"
WORKSPACE="$HOME/ai-workspace"
mkdir -p "$WORKSPACE"
chmod 750 "$WORKSPACE"
info "Workspace : $WORKSPACE"

step "Service systemd (optionnel)"
SERVICE_FILE="$HOME/.config/systemd/user/local-ai.service"
mkdir -p "$(dirname "$SERVICE_FILE")"
cat > "$SERVICE_FILE" << SVCEOF
[Unit]
Description=Local AI System
After=network.target

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
ExecStart=$VENV/bin/python3 $SCRIPT_DIR/main.py --host 127.0.0.1 --port 8080
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
SVCEOF
systemctl --user daemon-reload 2>/dev/null || true
systemctl --user enable local-ai.service 2>/dev/null || true
info "Service systemd configuré (local-ai)"

echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${GREEN}║         Installation terminée !               ║${RESET}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "  ${BOLD}Lancer :${RESET}"
echo -e "    cd $SCRIPT_DIR"
echo -e "    ./start.sh              ${AMBER}# port 8080 par défaut${RESET}"
echo -e "    ./start.sh 9090         ${AMBER}# port personnalisé${RESET}"
echo ""
echo -e "  ${BOLD}Ou manuellement :${RESET}"
echo -e "    source .venv/bin/activate"
echo -e "    python3 main.py --port 8080"
echo ""
echo -e "  ${BOLD}Service systemd :${RESET}"
echo -e "    systemctl --user start local-ai"
echo -e "    systemctl --user status local-ai"
echo ""
echo -e "  ${BOLD}Interface :${RESET} http://127.0.0.1:8080"
echo ""
