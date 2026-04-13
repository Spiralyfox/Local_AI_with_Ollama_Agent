"""
Client asynchrone pour l'API Ollama locale.
v5.0 — client httpx persistant + streaming + retry automatique.

Corrections v5.0 :
  - system prompt transmis proprement à chaque appel
  - temperature et max_tokens passés en paramètre (plus de valeurs hardcodées)
  - retry automatique (1× avec délai 2s) sur ConnectError et ReadTimeout
  - chat_stream : timeout adaptatif (connect court, read long)
"""
import asyncio
import httpx
import json
from typing import AsyncGenerator
from .logger import get_logger

logger = get_logger("ollama")

OLLAMA_URL    = "http://localhost:11434"
_RETRY_DELAY  = 2.0   # secondes avant de retenter
_MAX_RETRIES  = 1      # nombre de retries automatiques


class OllamaClient:
    def __init__(self, base_url: str = OLLAMA_URL, timeout: int = 300):
        self.base_url = base_url
        self.timeout  = timeout
        # Client persistant — connexion TCP réutilisée pour tous les appels
        self._client  = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=10),
        )

    # ─────────────────────────────────────────────────────────────
    # API publique
    # ─────────────────────────────────────────────────────────────

    async def chat(self, model: str, prompt: str, system: str = "",
                   temperature: float = 0.2, max_tokens: int = 8192) -> str:
        """Envoie un message et retourne la réponse complète."""
        payload = self._build_payload(model, prompt, system, temperature, max_tokens, stream=False)
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = await self._client.post(f"{self.base_url}/api/chat", json=payload)
                resp.raise_for_status()
                return resp.json()["message"]["content"]
            except httpx.ConnectError:
                if attempt < _MAX_RETRIES:
                    logger.warning(f"Ollama non joignable, retry dans {_RETRY_DELAY}s…")
                    await asyncio.sleep(_RETRY_DELAY)
                    continue
                logger.error("Ollama non joignable — lancez : ollama serve")
                return json.dumps({"error": "ollama_unavailable"})
            except httpx.ReadTimeout:
                if attempt < _MAX_RETRIES:
                    logger.warning(f"Timeout ({self.timeout}s), retry…")
                    await asyncio.sleep(_RETRY_DELAY)
                    continue
                logger.error(f"Timeout ({self.timeout}s) dépassé — modèle trop lent ?")
                return json.dumps({"error": "timeout"})
            except httpx.HTTPStatusError as e:
                logger.error(f"Erreur HTTP Ollama {e.response.status_code}: {e.response.text[:200]}")
                return json.dumps({"error": f"http_{e.response.status_code}"})
            except Exception as e:
                logger.error(f"Erreur Ollama inattendue: {e}")
                return json.dumps({"error": str(e)})
        return json.dumps({"error": "max_retries_exceeded"})

    async def chat_stream(self, model: str, prompt: str, system: str = "",
                          temperature: float = 0.2,
                          max_tokens: int = 8192) -> AsyncGenerator[str, None]:
        """
        Génère les tokens un par un via le streaming Ollama.
        Usage :
            full = ""
            async for token in client.chat_stream(...):
                full += token
        """
        payload = self._build_payload(model, prompt, system, temperature, max_tokens, stream=True)
        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with self._client.stream(
                    "POST", f"{self.base_url}/api/chat", json=payload
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            data  = json.loads(line)
                            token = data.get("message", {}).get("content", "")
                            if token:
                                yield token
                            if data.get("done"):
                                return
                        except json.JSONDecodeError:
                            continue
                return  # succès, on sort
            except httpx.ConnectError:
                if attempt < _MAX_RETRIES:
                    logger.warning(f"Ollama non joignable (stream), retry dans {_RETRY_DELAY}s…")
                    await asyncio.sleep(_RETRY_DELAY)
                    continue
                logger.error("Ollama non joignable (stream)")
                yield json.dumps({"error": "ollama_unavailable"})
                return
            except httpx.ReadTimeout:
                if attempt < _MAX_RETRIES:
                    logger.warning("Timeout stream, retry…")
                    await asyncio.sleep(_RETRY_DELAY)
                    continue
                logger.error(f"Timeout streaming ({self.timeout}s)")
                yield json.dumps({"error": "timeout"})
                return
            except Exception as e:
                logger.error(f"Erreur streaming Ollama: {e}")
                yield json.dumps({"error": str(e)})
                return

    async def list_models(self) -> list[str]:
        try:
            resp = await self._client.get(f"{self.base_url}/api/tags")
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            return []

    async def is_alive(self) -> bool:
        try:
            r = await self._client.get(f"{self.base_url}/", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    async def aclose(self):
        """Ferme proprement le client HTTP (à appeler au shutdown de l'app)."""
        await self._client.aclose()

    # ─────────────────────────────────────────────────────────────
    # Interne
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _build_payload(model: str, prompt: str, system: str,
                       temperature: float, max_tokens: int, stream: bool) -> dict:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return {
            "model":    model,
            "messages": messages,
            "stream":   stream,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
