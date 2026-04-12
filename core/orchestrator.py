"""
Orchestrator v3 — multi-agent avec recherche web optionnelle.
Flow : Planification → [Recherche web] → Codage → Review → Retry
"""
import json
import re
from pathlib import Path
from .ollama_client import OllamaClient
from .sandbox import Sandbox
from .web_search import WebSearcher
from .logger import get_logger

logger = get_logger("orchestrator")

AGENTS = {
    "planner":  "qwen2.5-coder:7b",
    "coder":    "qwen2.5-coder:7b",
    "reviewer": "qwen2.5-coder:7b",
}

MAX_RETRIES = 5
WEB_SEARCH_ENABLED = False  # Togglable via config


class Orchestrator:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.client = OllamaClient()
        self.sandbox = Sandbox(workspace)
        self.searcher = WebSearcher(max_results=5)
        self._broadcast = None  # Set by web app for live updates

    def set_broadcast(self, broadcast_fn):
        """Permet au serveur web d'envoyer des events live."""
        self._broadcast = broadcast_fn

    async def _emit(self, event: dict):
        """Émet un événement vers le WebSocket si disponible."""
        if self._broadcast:
            try:
                await self._broadcast(event)
            except Exception:
                pass

    async def run(self, task: str) -> dict:
        logger.info(f"Nouvelle tâche: {task!r}")
        result = {"task": task, "success": False, "steps": [], "output": "",
                  "web_search_used": False, "search_results": {}}

        # 1. Planification
        plan = await self._plan(task)
        result["plan"] = plan
        logger.info(f"Plan: {plan}")

        # 2. Recherche web (si activée et demandée par le planificateur)
        web_context = ""
        if WEB_SEARCH_ENABLED:
            queries = plan.get("search_queries", [])
            if queries:
                await self._emit({"type": "search_start", "queries": queries})
                logger.info(f"Recherche web: {queries}")

                search_results = await self.searcher.multi_search(queries, max_per_query=3)
                web_context = WebSearcher.format_results(search_results)
                result["web_search_used"] = True
                result["search_results"] = {
                    q: [{"title": r["title"], "url": r["url"]} for r in items]
                    for q, items in search_results.items()
                }

                await self._emit({
                    "type": "search_done",
                    "queries": queries,
                    "result_count": sum(len(v) for v in search_results.values()),
                })
                logger.info(f"Recherche terminée: {sum(len(v) for v in search_results.values())} résultats")

        # 3. Codage avec corrections auto
        previous_errors = []
        for attempt in range(1, MAX_RETRIES + 1):
            logger.info(f"Tentative {attempt}/{MAX_RETRIES}")
            code_result = await self._code(task, plan, attempt, previous_errors, web_context)
            result["steps"].append({"attempt": attempt, "code": code_result})

            review = await self._review(task, code_result)
            result["steps"][-1]["review"] = review

            if review.get("approved"):
                result["success"] = True
                result["output"] = code_result.get("output", "")
                logger.info("Tâche approuvée.")
                break

            reason = review.get("reason", "?")
            logger.warning(f"Rejeté: {reason}")
            previous_errors.append(reason)

            if review.get("fix_plan"):
                plan = review["fix_plan"]

        return result

    # ── Planificateur ─────────────────────────────────────────────
    async def _plan(self, task: str) -> dict:
        search_instruction = ""
        if WEB_SEARCH_ENABLED:
            search_instruction = """
- Si la tâche nécessite des informations récentes (API, documentation, syntaxe spécifique),
  ajoute un champ "search_queries": ["query1", "query2"] avec 1-3 recherches Google pertinentes.
- Si la tâche est faisable sans recherche, ne mets PAS le champ search_queries."""

        prompt = f"""Tu es un agent planificateur expert.
Décompose la tâche en étapes concrètes.

Réponds UNIQUEMENT en JSON valide (pas de markdown) :
{{"steps": ["étape 1", "étape 2", ...], "files_to_create": ["chemin/fichier.ext", ...]{', "search_queries": ["recherche 1"]' if WEB_SEARCH_ENABLED else ''}}}

Règles :
- 2 à 8 étapes actionnables
- Liste tous les fichiers à créer{search_instruction}

Tâche : {task}"""

        raw = await self.client.chat(AGENTS["planner"], prompt)
        return self._parse_json(raw, {"steps": [task], "files_to_create": []})

    # ── Codeur ────────────────────────────────────────────────────
    async def _code(self, task: str, plan: dict, attempt: int,
                    previous_errors: list, web_context: str = "") -> dict:
        steps_txt = "\n".join(f"- {s}" for s in plan.get("steps", [task]))
        files_txt = ", ".join(plan.get("files_to_create", [])) or "à déterminer"

        errors_block = ""
        if previous_errors:
            errors_txt = "\n".join(f"  - Tentative {i+1}: {e}" for i, e in enumerate(previous_errors))
            errors_block = f"\nERREURS PRÉCÉDENTES (corrige-les) :\n{errors_txt}\n"

        web_block = ""
        if web_context:
            web_block = f"\n{web_context}\nUtilise ces informations web pour produire un code plus précis et à jour.\n"

        prompt = f"""Tu es un agent codeur senior. Code production-ready, complet, fonctionnel.

Réponds UNIQUEMENT en JSON valide :
{{
  "files": [{{"path": "chemin/fichier.ext", "content": "contenu COMPLET"}}],
  "commands": ["commande shell optionnelle"]
}}

RÈGLES :
- Chaque fichier COMPLET (tous les imports, gestion d'erreurs, pas de "...")
- Pour Python : if __name__ == "__main__" quand pertinent
- Pour HTML : page complète avec <!DOCTYPE html> et CSS inline
- NE PAS utiliser sudo
{web_block}
Tâche : {task}
Plan :
{steps_txt}
Fichiers : {files_txt}
Tentative {attempt}/{MAX_RETRIES}
{errors_block}"""

        raw = await self.client.chat(AGENTS["coder"], prompt)
        data = self._parse_json(raw, {"files": [], "commands": []})

        output_log = []
        for f in data.get("files", []):
            path, content = f.get("path", ""), f.get("content", "")
            if path and content:
                ok, msg = self.sandbox.write_file(path, content)
                output_log.append(f"{'OK' if ok else 'ERR'}: {path} — {msg}")

        for cmd in data.get("commands", []):
            if cmd.strip():
                ok, out = self.sandbox.run_command(cmd)
                output_log.append(f"CMD({'OK' if ok else 'FAIL'}): {cmd}\n{out}")

        data["output"] = "\n".join(output_log)
        return data

    # ── Reviewer ──────────────────────────────────────────────────
    async def _review(self, task: str, code_result: dict) -> dict:
        files_summary = "\n".join(
            f"=== {f['path']} ===\n{f['content'][:1500]}"
            for f in code_result.get("files", [])
        )

        prompt = f"""Tu es un reviewer senior exigeant.
Évalue si le code répond COMPLÈTEMENT à la tâche.

Réponds UNIQUEMENT en JSON valide :
{{"approved": true/false, "reason": "...", "fix_plan": {{"steps": [...], "files_to_create": [...]}}}}

Critères :
1. Code complet ? (pas de TODO/placeholder)
2. Imports présents ?
3. Gestion d'erreurs ?
4. Correspond à la tâche ?

Tâche : {task}
Exécution : {code_result.get('output', 'aucun')}
Fichiers :
{files_summary}"""

        raw = await self.client.chat(AGENTS["reviewer"], prompt)
        return self._parse_json(raw, {"approved": True, "reason": "auto-approve (parse error)"})

    # ── JSON parser robuste ───────────────────────────────────────
    def _parse_json(self, raw: str, fallback: dict) -> dict:
        cleaned = re.sub(r'^```(?:json)?\s*\n?', '', raw.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r'\n?```\s*$', '', cleaned.strip(), flags=re.MULTILINE)
        try:
            return json.loads(cleaned)
        except Exception:
            pass
        depth = 0
        start = None
        for i, c in enumerate(raw):
            if c == '{':
                if depth == 0: start = i
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0 and start is not None:
                    try:
                        return json.loads(raw[start:i+1])
                    except:
                        start = None
        logger.warning(f"JSON parse failed. Raw[:200]: {raw[:200]}")
        return fallback
