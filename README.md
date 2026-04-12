# Local AI System

Assistant IA local multi-agent, 100 % offline, tournant sur Ollama.

---

## Installation rapide

```bash
# 1. Extraire et entrer dans le dossier
unzip local-ai-system.zip
cd local-ai-system

# 2. Lancer l'installation automatique
chmod +x scripts/install.sh
./scripts/install.sh
```

L'installateur vérifie Python 3.10+, installe Ollama si absent, télécharge `qwen2.5-coder:7b` (~4 Go), crée le virtualenv et installe les dépendances.

### Installation manuelle (si tu préfères)

```bash
cd local-ai-system

# Créer le virtualenv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Installer Ollama (si pas déjà fait)
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &          # dans un terminal séparé
ollama pull qwen2.5-coder:7b
```

---

## Lancement

### Méthode simple : start.sh

```bash
./start.sh              # → http://127.0.0.1:8080
./start.sh 9090         # → http://127.0.0.1:9090
```

### Méthode manuelle

```bash
source .venv/bin/activate

python3 main.py                          # port 8080 (défaut)
python3 main.py --port 9090             # port 9090
python3 main.py --port 9090 --host 0.0.0.0   # accessible depuis le réseau local
```

### Options disponibles

| Option       | Défaut        | Description |
|-------------|---------------|-------------|
| `--port`    | `8080`        | Port d'écoute du serveur web |
| `--host`    | `127.0.0.1`   | Adresse d'écoute (`0.0.0.0` pour réseau local) |
| `--reload`  | off           | Hot-reload en développement |

### Service systemd (démarrage auto)

```bash
systemctl --user start local-ai
systemctl --user status local-ai
systemctl --user stop local-ai
journalctl --user -u local-ai -f       # voir les logs
```

Pour changer le port du service, éditer `~/.config/systemd/user/local-ai.service` et modifier `--port`.

---

## Mode CLI (sans interface web)

```bash
source .venv/bin/activate
python3 cli.py "Crée un serveur HTTP Python avec endpoint /hello"
python3 cli.py "Génère un script qui liste les fichiers .py" -v   # mode verbose
```

---

## Structure du projet

```
local-ai-system/
├── start.sh               ← Script de lancement rapide
├── main.py                ← Point d'entrée (web)
├── cli.py                 ← Mode terminal
├── requirements.txt
├── config/
│   └── config.yaml        ← Paramètres modèles, sandbox, web
├── core/
│   ├── orchestrator.py    ← Boucle multi-agent
│   ├── ollama_client.py   ← Client HTTP async pour Ollama
│   ├── sandbox.py         ← Sécurité fichiers/commandes
│   └── logger.py
├── web/
│   ├── app.py             ← API FastAPI + WebSocket
│   └── index.html         ← Interface terminal-style
├── scripts/
│   └── install.sh         ← Installation one-shot
└── logs/
    └── agent.log
```

## Architecture des agents

```
Utilisateur (tâche texte)
        │
        ▼
┌─────────────────┐
│   Orchestrator  │  ← coordonne la boucle (max 3 tentatives)
└────────┬────────┘
         │
    ┌────┴────────────────────────┐
    │                             │
    ▼                             │
┌──────────┐                      │
│ Planner  │  décompose la tâche  │
│  Agent   │  en étapes + fichiers│
└────┬─────┘                      │
     │ plan JSON                  │
     ▼                            │
┌──────────┐                      │
│  Coder   │  génère le code      │
│  Agent   │  écrit dans sandbox  │
└────┬─────┘                      │
     │ code + sortie              │
     ▼                            │
┌──────────┐                      │
│ Reviewer │  évalue le résultat  │
│  Agent   │  approuve ou corrige ├──(rejeté)──┘
└──────────┘
     │ approuvé
     ▼
  ✅ Résultat
```

## Sécurité sandbox

- Fichiers écrits dans `~/ai-workspace` uniquement
- Path traversal (`../`) détecté et bloqué
- Extensions autorisées : `.py .js .html .css .json .yaml .sh ...`
- Commandes interdites : `sudo`, `rm -rf /`, `curl|sh`, etc.
- Exécution root impossible
- Timeout 30s par commande shell

## Modèles recommandés

| Modèle | Usage | RAM |
|--------|-------|-----|
| `qwen2.5-coder:7b` | Codage, review | 6 Go |
| `qwen2.5-coder:14b` | Qualité supérieure | 12 Go |
| `deepseek-r1:7b` | Planification/raisonnement | 6 Go |
| `deepseek-r1:14b` | Planification avancée | 12 Go |

Changer de modèle : onglet **Modèles** dans l'interface web, ou éditer `config/config.yaml`.

## Exemples de tâches

```
Crée un serveur HTTP Python avec un endpoint /hello retournant du JSON
Génère un fichier HTML avec un formulaire de contact stylisé
Écris un script Python qui surveille l'espace disque et envoie une alerte
Crée un module Python de chiffrement AES avec tests unitaires
Génère un README.md pour un projet de todo-list REST API
```

## Dépannage

| Problème | Solution |
|----------|----------|
| `python: command not found` | Utiliser `python3` au lieu de `python` |
| `.venv not found` | Lancer `./scripts/install.sh` ou créer manuellement le venv |
| `Ollama hors ligne` | Lancer `ollama serve` dans un terminal séparé |
| Port déjà utilisé | `./start.sh 9090` pour changer de port |
| Modèle trop lent | Essayer un modèle plus petit ou vérifier la RAM dispo |
