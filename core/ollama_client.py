"""
Client asynchrone pour l'API Ollama locale.
Supporte les timeouts longs pour gros modèles.
"""
import httpx
import json
from .logger import get_logger

logger = get_logger("ollama")

OLLAMA_URL = "http://localhost:11434"


class OllamaClient:
    def __init__(self, base_url: str = OLLAMA_URL, timeout: int = 300):
        self.base_url = base_url
        self.timeout = timeout

    async def chat(self, model: str, prompt: str, system: str = "",
                   temperature: float = 0.2, max_tokens: int = 8192) -> str:
        """Envoie un message et retourne la réponse en texte brut."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.base_url}/api/chat", json=payload)
                resp.raise_for_status()
                return resp.json()["message"]["content"]
        except httpx.ConnectError:
            logger.error("Ollama non joignable — lancez : ollama serve")
            return json.dumps({"error": "ollama_unavailable"})
        except httpx.ReadTimeout:
            logger.error(f"Timeout ({self.timeout}s) — augmentez le timeout ou utilisez un modèle plus petit")
            return json.dumps({"error": "timeout"})
        except Exception as e:
            logger.error(f"Erreur Ollama: {e}")
            return json.dumps({"error": str(e)})

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                return [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            return []

    async def is_alive(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{self.base_url}/")
                return r.status_code == 200
        except Exception:
            return False
