"""
Module de recherche web via DuckDuckGo.
Pas de clé API, pas de limite stricte, gratuit.

Fix v5.1 :
  - multi_search séquentiel (au lieu de parallèle) pour éviter le rate-limit DDG
  - Retry avec backoff exponentiel par requête (3 tentatives)
  - Délai aléatoire entre requêtes (1.5-3s) pour éviter le ban
  - Timeout explicite sur DDGS
  - Log des vraies erreurs (plus de silence sur les exceptions)
"""
import asyncio
import random
import time
from .logger import get_logger

logger = get_logger("web_search")


class WebSearcher:
    """Recherche web asynchrone via DuckDuckGo."""

    def __init__(self, max_results: int = 5):
        self.max_results = max_results
        self._available = None

    async def is_available(self) -> bool:
        """Vérifie si le module duckduckgo_search est installé."""
        if self._available is not None:
            return self._available
        try:
            from duckduckgo_search import DDGS  # noqa: F401
            self._available = True
        except ImportError:
            logger.warning("duckduckgo-search non installé. pip install duckduckgo-search")
            self._available = False
        return self._available

    async def search(self, query: str, max_results: int = None) -> list[dict]:
        """
        Recherche DuckDuckGo avec retry (3 tentatives, backoff exponentiel).
        Chaque résultat : {"title": ..., "url": ..., "body": ...}
        """
        if not await self.is_available():
            return []

        n = max_results or self.max_results

        for attempt in range(3):
            try:
                results = await asyncio.to_thread(self._sync_search, query, n)
                logger.info(f"Recherche '{query}' -> {len(results)} résultats")
                return results
            except Exception as e:
                wait = (attempt + 1) * 2.0 + random.uniform(0.5, 1.5)
                logger.warning(
                    f"Recherche '{query}' tentative {attempt+1}/3 échouée: {type(e).__name__}: {e}. "
                    f"Attente {wait:.1f}s..."
                )
                if attempt < 2:
                    await asyncio.sleep(wait)

        logger.error(f"Recherche '{query}' abandonnée après 3 tentatives")
        return []

    def _sync_search(self, query: str, max_results: int) -> list[dict]:
        """Recherche synchrone avec délai anti-rate-limit."""
        from duckduckgo_search import DDGS

        # Petit délai systématique pour éviter le rate-limit
        time.sleep(0.3 + random.uniform(0, 0.4))

        # timeout=20 évite les blocages infinis
        with DDGS(timeout=20) as ddgs:
            results = []
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "url":   r.get("href",  r.get("link", "")),
                    "body":  r.get("body",  r.get("snippet", "")),
                })
            return results

    async def multi_search(
        self, queries: list[str], max_per_query: int = 3
    ) -> dict[str, list[dict]]:
        """
        Exécute plusieurs recherches SÉQUENTIELLEMENT avec délai entre chacune.

        IMPORTANT : on ne parallélise plus car DuckDuckGo rate-limite immédiatement
        les requêtes parallèles et retourne 0 résultats sans lever d'exception.
        """
        if not await self.is_available():
            return {}

        out: dict[str, list[dict]] = {}

        for i, q in enumerate(queries):
            out[q] = await self.search(q, max_per_query)

            # Délai entre les requêtes (sauf après la dernière)
            if i < len(queries) - 1:
                delay = 1.5 + random.uniform(0.5, 1.5)
                logger.debug(f"Délai inter-requêtes: {delay:.1f}s")
                await asyncio.sleep(delay)

        return out

    @staticmethod
    def format_results(results: dict[str, list[dict]], max_chars: int = 4000) -> str:
        """Formate les résultats de recherche en texte pour injection dans un prompt."""
        if not results:
            return ""

        lines = ["=== RÉSULTATS DE RECHERCHE WEB ===\n"]
        total = 0
        for query, items in results.items():
            lines.append(f'Recherche : "{query}"')
            if not items:
                lines.append("  (aucun résultat)\n")
                continue
            for item in items:
                entry = (
                    f"  * {item['title']}\n"
                    f"    {item['body'][:250]}\n"
                    f"    Source: {item['url']}\n"
                )
                if total + len(entry) > max_chars:
                    lines.append("  ... (résultats tronqués)\n")
                    break
                lines.append(entry)
                total += len(entry)
            lines.append("")

        lines.append("=== FIN DES RÉSULTATS ===")
        return "\n".join(lines)
