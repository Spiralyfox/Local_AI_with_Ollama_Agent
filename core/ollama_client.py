"""
Client asynchrone pour l'API Ollama locale.
v4.1 — client httpx persistant (plus de reconnexion à chaque appel)
      + chat_stream() pour affichage token par token.
"""
import httpx
import json
from typing import AsyncGenerator
from .logger import get_logger

logger = get_logger("ollama")

OLLAMA_URL = "http://localhost:11434"


class OllamaClient:
    def __init__(self, base_url: str = OLLAMA_URL, timeout: int = 300):
        self.base_url = base_url
        self.timeout = timeout
        # Client persistant — une seule connexion TCP réutilisée pour tous les appels
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10))

    async def chat(self, model: str, prompt: str, system: str = "",
                   temperature: float = 0.2, max_tokens: int = 8192) -> str:
        """Envoie un message et retourne la réponse complète en texte brut."""
        payload = self._build_payload(model, prompt, system, temperature, max_tokens, stream=False)
        try:
            resp = await self._client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            return resp.json()["message"]["content"]
        except httpx.ConnectError:
            logger.error("Ollama non joignable — lancez : ollama serve")
            return json.dumps({"error": "ollama_unavailable"})
        except httpx.ReadTimeout:
            logger.error(f"Timeout ({self.timeout}s) — modèle trop lent ou timeout trop court")
            return json.dumps({"error": "timeout"})
        except Exception as e:
            logger.error(f"Erreur Ollama: {e}")
            return json.dumps({"error": str(e)})

    async def chat_stream(self, model: str, prompt: str, system: str = "",
                          temperature: float = 0.2,
                          max_tokens: int = 8192) -> AsyncGenerator[str, None]:
        """
        Génère les tokens un par un via le streaming Ollama.
        Usage :
            full = ""
            async for token in client.chat_stream(...):
                full += token
                await emit_token(token)
        """
        payload = self._build_payload(model, prompt, system, temperature, max_tokens, stream=True)
        try:
            async with self._client.stream("POST", f"{self.base_url}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        token = data.get("message", {}).get("content", "")
                        if token:
                            yield token
                        if data.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue
        except httpx.ConnectError:
            logger.error("Ollama non joignable (stream)")
            yield json.dumps({"error": "ollama_unavailable"})
        except httpx.ReadTimeout:
            logger.error(f"Timeout streaming ({self.timeout}s)")
            yield json.dumps({"error": "timeout"})
        except Exception as e:
            logger.error(f"Erreur streaming Ollama: {e}")
            yield json.dumps({"error": str(e)})

    async def list_models(self) -> list[str]:
        try:
            resp = await self._client.get(f"{self.base_url}/api/tags")
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            return []

    async def is_alive(self) -> bool:
        try:
            r = await self._client.get(f"{self.base_url}/")
            return r.status_code == 200
        except Exception:
            return False

    async def aclose(self):
        """Ferme proprement le client HTTP (à appeler au shutdown de l'app)."""
        await self._client.aclose()

    # ── Interne ──────────────────────────────────────────────────

    @staticmethod
    def _build_payload(model, prompt, system, temperature, max_tokens, stream):
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return {
            "model": model,
            "messages": messages,
            "stream": stream,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
