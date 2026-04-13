# Local AI System

Assistant IA local multi-agent, 100 % offline, tournant sur Ollama.

---

## Installation rapide

```bash
unzip local-ai-system.zip
cd local-ai-system
chmod +x scripts/install.sh start.sh
./scripts/install.sh
```

### Installation manuelle

```bash
cd local-ai-system
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Ollama (si pas déjà installé)
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &
ollama pull qwen2.5-coder:7b
```

---

## Lancement

```bash
./start.sh              # port 8080
./start.sh 9090         # port 9090

# Ou manuellement :
source .venv/bin/activate
python3 main.py --port 8080
python3 main.py --port 9090 --host 0.0.0.0   # réseau local
```

---

## Guide des modèles

### Modèles Code (pour l'agent Codeur)

| Modèle | Params | Taille | VRAM | Vitesse | Qualité |
|--------|--------|--------|------|---------|---------|
| `qwen2.5-coder:1.5b` | 1.5B | 1.0 GB | 2 GB | ⚡⚡⚡ | ★★☆☆☆ |
| `qwen2.5-coder:3b` | 3B | 1.9 GB | 4 GB | ⚡⚡⚡ | ★★★☆☆ |
| **`qwen2.5-coder:7b`** | **7B** | **4.7 GB** | **6 GB** | **⚡⚡** | **★★★★☆** |
| `qwen2.5-coder:14b` | 14B | 9.0 GB | 12 GB | ⚡ | ★★★★☆ |
| `qwen2.5-coder:32b` | 32B | 20 GB | 24 GB | 🐢 | ★★★★★ |
| `starcoder2:3b` | 3B | 1.7 GB | 4 GB | ⚡⚡⚡ | ★★★☆☆ |
| `starcoder2:7b` | 7B | 4.0 GB | 6 GB | ⚡⚡ | ★★★☆☆ |
| `starcoder2:15b` | 15B | 9.0 GB | 12 GB | ⚡ | ★★★★☆ |
| `codellama:7b` | 7B | 3.8 GB | 6 GB | ⚡⚡ | ★★★☆☆ |
| `codellama:13b` | 13B | 7.4 GB | 10 GB | ⚡ | ★★★★☆ |
| `codellama:34b` | 34B | 19 GB | 24 GB | 🐢 | ★★★★☆ |
| `yi-coder:9b` | 9B | 5.0 GB | 8 GB | ⚡⚡ | ★★★★☆ |
| `deepseek-coder-v2:16b` | 16B MoE | 8.9 GB | 12 GB | ⚡ | ★★★★☆ |

### Modèles Raisonnement (pour l'agent Planificateur)

| Modèle | Params | Taille | VRAM | Vitesse | Qualité |
|--------|--------|--------|------|---------|---------|
| `deepseek-r1:1.5b` | 1.5B | 1.1 GB | 2 GB | ⚡⚡⚡ | ★★☆☆☆ |
| **`deepseek-r1:7b`** | **7B** | **4.7 GB** | **6 GB** | **⚡⚡** | **★★★★☆** |
| `deepseek-r1:8b` | 8B | 4.9 GB | 6 GB | ⚡⚡ | ★★★★☆ |
| `deepseek-r1:14b` | 14B | 9.0 GB | 12 GB | ⚡ | ★★★★★ |
| `deepseek-r1:32b` | 32B | 20 GB | 24 GB | 🐢 | ★★★★★ |
| `deepseek-r1:70b` | 70B | 43 GB | 48 GB | 🐢🐢 | ★★★★★ |

### Modèles Généraux (pour le Reviewer ou usage mixte)

| Modèle | Params | Taille | VRAM | Vitesse | Qualité |
|--------|--------|--------|------|---------|---------|
| `qwen3:4b` | 4B | 2.6 GB | 4 GB | ⚡⚡⚡ | ★★★☆☆ |
| `qwen3:8b` | 8B | 5.2 GB | 6 GB | ⚡⚡ | ★★★★☆ |
| `qwen3:14b` | 14B | 9.2 GB | 12 GB | ⚡ | ★★★★☆ |
| `qwen3:30b` | 30B | 19 GB | 24 GB | 🐢 | ★★★★★ |
| `qwen3:32b` | 32B | 20 GB | 24 GB | 🐢 | ★★★★★ |
| `llama3.1:8b` | 8B | 4.7 GB | 6 GB | ⚡⚡ | ★★★★☆ |
| `llama3.2:3b` | 3B | 2.0 GB | 4 GB | ⚡⚡⚡ | ★★★☆☆ |
| `gemma2:9b` | 9B | 5.5 GB | 8 GB | ⚡⚡ | ★★★★☆ |
| `gemma2:27b` | 27B | 16 GB | 20 GB | 🐢 | ★★★★★ |
| `mistral:7b` | 7B | 4.1 GB | 6 GB | ⚡⚡ | ★★★★☆ |
| `phi4:14b` | 14B | 9.1 GB | 12 GB | ⚡ | ★★★★☆ |

### Configurations recommandées

| RAM GPU | Planner | Coder | Reviewer |
|---------|---------|-------|----------|
| **4 GB** | `deepseek-r1:1.5b` | `qwen2.5-coder:3b` | `qwen3:4b` |
| **6 GB** | `deepseek-r1:7b` | `qwen2.5-coder:7b` | `qwen2.5-coder:7b` |
| **8 GB** | `deepseek-r1:7b` | `qwen2.5-coder:7b` | `qwen3:8b` |
| **12 GB** | `deepseek-r1:14b` | `qwen2.5-coder:14b` | `qwen3:14b` |
| **24 GB** | `deepseek-r1:32b` | `qwen2.5-coder:32b` | `qwen3:30b` |
| **CPU only** | `deepseek-r1:1.5b` | `qwen2.5-coder:1.5b` | `qwen3:1.7b` |

---

## Mode CLI

```bash
source .venv/bin/activate
python3 cli.py "Crée un serveur HTTP Python avec /hello"
python3 cli.py "Génère un dashboard HTML avec graphiques" -v
```

## Structure

```
local-ai-system/
├── start.sh               ← Lancement rapide
├── main.py                ← Serveur web
├── cli.py                 ← Mode terminal
├── config/config.yaml     ← Configuration
├── core/
│   ├── orchestrator.py    ← Boucle multi-agent (5 tentatives)
│   ├── ollama_client.py   ← Client Ollama async
│   ├── sandbox.py         ← Sécurité fichiers/commandes
│   └── logger.py
├── web/
│   ├── app.py             ← API FastAPI + catalogue hardcodé
│   └── index.html         ← Interface web
└── scripts/install.sh     ← Installation
```

## Dépannage

| Problème | Solution |
|----------|----------|
| `python: not found` | Utiliser `python3` |
| `.venv not found` | `./scripts/install.sh` ou `python3 -m venv .venv` |
| Ollama hors ligne | `ollama serve` dans un autre terminal |
| Port occupé | `./start.sh 9090` |
| Modèle trop lent | Modèle plus petit ou vérifier VRAM |
| Erreur JSON du modèle | Augmenter max_tokens dans Config |
| Projet trop gros | Augmenter tentatives et tokens dans Config |

## Changelog

### v4.1 — Streaming & stabilité
- **Client httpx persistant** : `OllamaClient` maintient une connexion TCP réutilisée — fini la reconnexion à chaque appel LLM
- **Streaming token par token** : le codeur affiche sa réponse en direct dans le terminal web (ligne live bordée en bleu)
- **Limite review étendue** : le reviewer voit désormais jusqu'à 4000 chars par fichier (anciennement 1500) — meilleure qualité de relecture
- **Protection tâche unique** : un verrou `asyncio.Lock` empêche deux tâches de tourner en parallèle sur le même orchestrateur ; retour HTTP 409 si déjà occupé
- **Shutdown propre** : le client httpx est fermé correctement à l'arrêt de FastAPI (`@on_event("shutdown")`)

