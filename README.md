# Local AI System

Assistant IA local multi-agent, 100 % offline, tournant sur Ollama.

## Architecture

```
local-ai-system/
├── main.py                  ← Point d'entrée (web)
├── cli.py                   ← Mode terminal
├── requirements.txt
├── config/
│   └── config.yaml          ← Paramètres modèles, sandbox, web
├── core/
│   ├── orchestrator.py      ← Boucle multi-agent
│   ├── ollama_client.py     ← Client HTTP async pour Ollama
│   ├── sandbox.py           ← Sécurité fichiers/commandes
│   └── logger.py
├── web/
│   ├── app.py               ← API FastAPI + WebSocket
│   └── index.html           ← Interface terminal-style
├── agents/                  ← (extensible : agents spécialisés)
├── logs/
│   └── agent.log
└── scripts/
    └── install.sh           ← Installation one-shot
```

## Installation

```bash
# 1. Cloner / copier le projet
cd ~/local-ai-system

# 2. Lancer l'installation automatique
chmod +x scripts/install.sh
./scripts/install.sh
```

L'installateur :
- vérifie Python 3.12+
- installe Ollama si absent
- télécharge `qwen2.5-coder:7b` (~4 Go)
- crée un virtualenv Python
- configure un service systemd

## Lancement

### Interface web
```bash
source .venv/bin/activate
python main.py
# → http://127.0.0.1:8080
```

### Mode CLI
```bash
source .venv/bin/activate
python cli.py "Crée un serveur HTTP Python avec endpoint /hello"
python cli.py "Génère un script qui liste les fichiers .py et compte leurs lignes"
```

### Service systemd (démarrage auto)
```bash
systemctl --user start local-ai
systemctl --user status local-ai
journalctl --user -u local-ai -f
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

- Tous les fichiers écrits dans `~/ai-workspace` uniquement
- Path traversal (`../`) détecté et bloqué
- Extensions autorisées : `.py .js .html .css .json .yaml .sh ...`
- Commandes interdites : `sudo`, `rm -rf /`, `curl|sh`, `/etc/shadow`...
- Exécution root impossible
- Timeout 30 s par commande shell

## Modèles supportés

| Modèle | Usage recommandé | RAM |
|--------|-----------------|-----|
| `qwen2.5-coder:7b` | Codage, review | 6 Go |
| `qwen2.5-coder:14b` | Qualité supérieure | 12 Go |
| `deepseek-r1:7b` | Planification/raisonnement | 6 Go |
| `deepseek-r1:14b` | Planification avancée | 12 Go |

Changer de modèle : éditer `config/config.yaml` ou `core/orchestrator.py`.

## Ajouter un modèle
```bash
ollama pull deepseek-r1:7b
# Puis dans config/config.yaml :
# planner: "deepseek-r1:7b"
```

## Exemples de tâches

```
Crée un serveur HTTP Python avec un endpoint /hello retournant du JSON
Génère un fichier HTML avec un formulaire de contact stylisé
Écris un script Python qui surveille l'espace disque et envoie une alerte
Crée un module Python de chiffrement AES avec tests unitaires
Génère un README.md pour un projet de todo-list REST API
```

## Logs

```bash
tail -f logs/agent.log
```
