#!/usr/bin/env bash
# install.sh — Local AI System v2
# Idempotent : peut être relancé sans casser l'existant
set -euo pipefail

GREEN="\033[92m"; AMBER="\033[93m"; RED="\033[91m"; RESET="\033[0m"; BOLD="\033[1m"
info()  { echo -e "${GREEN}[✔]${RESET} $*"; }
warn()  { echo -e "${AMBER}[!]${RESET} $*"; }
error() { echo -e "${RED}[✘]${RESET} $*"; exit 1; }
step()  { echo -e "\n${BOLD}── $* ──${RESET}"; }

# Répertoire du script (= racine du projet)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

step "Vérifications"
[[ "$(id -u)" -eq 0 ]] && error "Ne pas lancer en root !"
python_version=$(python3 --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
major=$(echo "$python_version" | cut -d. -f1)
minor=$(echo "$python_version" | cut -d. -f2)
[[ "$major" -ge 3 && "$minor" -ge 12 ]] || error "Python 3.12+ requis (actuel: $python_version)"
info "Python $python_version"
[[ -f "$SCRIPT_DIR/requirements.txt" ]] || error "requirements.txt introuvable dans $SCRIPT_DIR"
info "requirements.txt trouvé"

step "Installation Ollama"
if ! command -v ollama &>/dev/null; then
  warn "Ollama non trouvé — installation..."
  curl -fsSL https://ollama.com/install.sh | sh
  info "Ollama installé"
else
  info "Ollama déjà présent : $(ollama --version)"
fi

if ! curl -sf http://localhost:11434/ &>/dev/null; then
  warn "Démarrage d'Ollama en background..."
  nohup ollama serve &>/tmp/ollama.log &
  sleep 3
fi

step "Téléchargement des modèles"
pull_model() {
  local model="$1"
  if ollama list 2>/dev/null | grep -q "^${model}"; then
    info "Modèle déjà présent : $model"
  else
    info "Téléchargement : $model..."
    ollama pull "$model"
  fi
}
pull_model "qwen2.5-coder:7b"

echo ""
warn "DeepSeek R1 est optionnel (4.7 GB). Installer ? [o/N]"
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

step "Service systemd"
SERVICE_FILE="$HOME/.config/systemd/user/local-ai.service"
mkdir -p "$(dirname "$SERVICE_FILE")"
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Local AI System
After=network.target

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
ExecStart=$VENV/bin/python $SCRIPT_DIR/main.py --host 127.0.0.1 --port 8081
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable local-ai.service 2>/dev/null || true
info "Service systemd configuré"

echo ""
echo -e "${BOLD}${GREEN}Installation terminée !${RESET}"
echo ""
echo -e "  Lancement     : ${BOLD}cd $SCRIPT_DIR && source .venv/bin/activate && python3 main.py --port 8081${RESET}"
echo -e "  Service       : ${BOLD}systemctl --user start local-ai${RESET}"
echo -e "  Interface web : ${BOLD}http://127.0.0.1:8081${RESET}"
echo ""
