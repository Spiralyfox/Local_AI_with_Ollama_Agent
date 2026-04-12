"""
Module de recherche web via DuckDuckGo.
Pas de clé API, pas de limite stricte, gratuit.
"""
import asyncio
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
            from duckduckgo_search import DDGS
            self._available = True
        except ImportError:
            logger.warning("duckduckgo-search non installé. pip install duckduckgo-search")
            self._available = False
        return self._available

    async def search(self, query: str, max_results: int = None) -> list[dict]:
        """
        Recherche DuckDuckGo et retourne une liste de résultats.
        Chaque résultat : {"title": ..., "url": ..., "body": ...}
        """
        if not await self.is_available():
            return []

        n = max_results or self.max_results

        try:
            # duckduckgo_search est synchrone, on l'exécute dans un thread
            results = await asyncio.to_thread(self._sync_search, query, n)
            logger.info(f"Recherche '{query}' → {len(results)} résultats")
            return results
        except Exception as e:
            logger.error(f"Erreur recherche '{query}': {e}")
            return []

    def _sync_search(self, query: str, max_results: int) -> list[dict]:
        """Recherche synchrone (appelée dans un thread)."""
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            results = []
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", r.get("link", "")),
                    "body": r.get("body", r.get("snippet", "")),
                })
            return results

    async def multi_search(self, queries: list[str], max_per_query: int = 3) -> dict[str, list[dict]]:
        """
        Exécute plusieurs recherches en parallèle.
        Retourne {query: [results], ...}
        """
        if not await self.is_available():
            return {}

        tasks = [self.search(q, max_per_query) for q in queries]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        out = {}
        for q, res in zip(queries, results_list):
            if isinstance(res, Exception):
                logger.error(f"Recherche '{q}' échouée: {res}")
                out[q] = []
            else:
                out[q] = res
        return out

    @staticmethod
    def format_results(results: dict[str, list[dict]], max_chars: int = 3000) -> str:
        """Formate les résultats de recherche en texte pour injection dans un prompt."""
        if not results:
            return ""

        lines = ["=== RÉSULTATS DE RECHERCHE WEB ===\n"]
        total = 0
        for query, items in results.items():
            lines.append(f"Recherche : \"{query}\"")
            if not items:
                lines.append("  (aucun résultat)\n")
                continue
            for item in items:
                entry = f"  • {item['title']}\n    {item['body'][:200]}\n    Source: {item['url']}\n"
                if total + len(entry) > max_chars:
                    lines.append("  ... (résultats tronqués)\n")
                    break
                lines.append(entry)
                total += len(entry)
            lines.append("")

        lines.append("=== FIN DES RÉSULTATS ===")
        return "\n".join(lines)
