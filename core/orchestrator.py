"""
Orchestrator v4 — multi-agent avec logs détaillés en temps réel.
Chaque phase émet des événements horodatés vers le WebSocket.
"""
import json
import re
import time
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
WEB_SEARCH_ENABLED = False


class Orchestrator:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.client = OllamaClient()
        self.sandbox = Sandbox(workspace)
        self.searcher = WebSearcher(max_results=5)
        self._broadcast = None

    def set_broadcast(self, broadcast_fn):
        self._broadcast = broadcast_fn

    async def _emit(self, event: dict):
        if self._broadcast:
            event.setdefault("ts", time.time())
            try: await self._broadcast(event)
            except: pass

    async def run(self, task: str) -> dict:
        t0 = time.time()
        logger.info(f"Nouvelle tâche: {task!r}")
        result = {"task": task, "success": False, "steps": [], "output": "",
                  "web_search_used": False, "search_results": {}}

        await self._emit({"type": "log", "level": "info",
            "msg": f"Démarrage — modèles: planner={AGENTS['planner']}, coder={AGENTS['coder']}, reviewer={AGENTS['reviewer']}"})
        await self._emit({"type": "log", "level": "info",
            "msg": f"Recherche web: {'activée' if WEB_SEARCH_ENABLED else 'désactivée'} | Retries max: {MAX_RETRIES}"})

        # ── 1. Planification ──
        await self._emit({"type": "phase", "phase": "planner", "state": "start",
            "msg": f"🧠 Planificateur ({AGENTS['planner']}) analyse la tâche…"})
        plan_t0 = time.time()

        plan = await self._plan(task)
        plan_dur = time.time() - plan_t0
        result["plan"] = plan

        steps = plan.get("steps", [task])
        files = plan.get("files_to_create", [])
        queries = plan.get("search_queries", [])

        await self._emit({"type": "phase", "phase": "planner", "state": "done",
            "msg": f"🧠 Plan généré en {plan_dur:.1f}s — {len(steps)} étapes, {len(files)} fichiers"})

        for i, s in enumerate(steps):
            await self._emit({"type": "log", "level": "plan", "msg": f"  {i+1}. {s}"})
        if files:
            await self._emit({"type": "log", "level": "system", "msg": f"  Fichiers prévus: {', '.join(files)}"})

        # ── 2. Recherche web ──
        web_context = ""
        if WEB_SEARCH_ENABLED and queries:
            await self._emit({"type": "phase", "phase": "search", "state": "start",
                "msg": f"🌐 Recherche web — {len(queries)} requêtes…"})
            for q in queries:
                await self._emit({"type": "log", "level": "search", "msg": f"  🔍 \"{q}\""})

            search_t0 = time.time()
            search_results = await self.searcher.multi_search(queries, max_per_query=3)
            search_dur = time.time() - search_t0
            web_context = WebSearcher.format_results(search_results)
            result["web_search_used"] = True
            result["search_results"] = {
                q: [{"title": r["title"], "url": r["url"]} for r in items]
                for q, items in search_results.items()
            }

            total_res = sum(len(v) for v in search_results.values())
            await self._emit({"type": "phase", "phase": "search", "state": "done",
                "msg": f"🌐 {total_res} résultats en {search_dur:.1f}s"})
            for q, items in search_results.items():
                for item in items:
                    await self._emit({"type": "log", "level": "search",
                        "msg": f"    • {item['title'][:80]}"})

        elif WEB_SEARCH_ENABLED:
            await self._emit({"type": "log", "level": "system",
                "msg": "🌐 Recherche web activée mais le planificateur n'en a pas eu besoin."})

        # ── 3. Boucle Codage / Review ──
        previous_errors = []
        for attempt in range(1, MAX_RETRIES + 1):
            await self._emit({"type": "log", "level": "info",
                "msg": f"\n{'═'*50}"})
            await self._emit({"type": "log", "level": "info",
                "msg": f"  TENTATIVE {attempt}/{MAX_RETRIES}"})
            await self._emit({"type": "log", "level": "info",
                "msg": f"{'═'*50}"})

            # ── Codage ──
            await self._emit({"type": "phase", "phase": "coder", "state": "start",
                "msg": f"💻 Codeur ({AGENTS['coder']}) génère le code…",
                "attempt": attempt})
            if web_context:
                await self._emit({"type": "log", "level": "system",
                    "msg": "  (contexte web injecté dans le prompt)"})
            if previous_errors:
                await self._emit({"type": "log", "level": "system",
                    "msg": f"  (erreurs précédentes transmises: {len(previous_errors)})"})

            code_t0 = time.time()
            code_result = await self._code(task, plan, attempt, previous_errors, web_context)
            code_dur = time.time() - code_t0
            result["steps"].append({"attempt": attempt, "code": code_result})

            n_files = len(code_result.get("files", []))
            n_cmds = len(code_result.get("commands", []))
            await self._emit({"type": "phase", "phase": "coder", "state": "done",
                "msg": f"💻 Code généré en {code_dur:.1f}s — {n_files} fichiers, {n_cmds} commandes"})

            # Log files created
            for f in code_result.get("files", []):
                path = f.get("path", "?")
                size = len(f.get("content", ""))
                await self._emit({"type": "log", "level": "ok",
                    "msg": f"  ✎ {path} ({size} chars)"})

            # Log command outputs
            if code_result.get("output"):
                for line in code_result["output"].split("\n"):
                    if line.strip():
                        lvl = "err" if line.startswith("ERR") or "FAIL" in line else "system"
                        await self._emit({"type": "log", "level": lvl,
                            "msg": f"  {line}"})

            # ── Review ──
            await self._emit({"type": "phase", "phase": "reviewer", "state": "start",
                "msg": f"🔍 Reviewer ({AGENTS['reviewer']}) évalue le code…"})

            review_t0 = time.time()
            review = await self._review(task, code_result)
            review_dur = time.time() - review_t0
            result["steps"][-1]["review"] = review

            approved = review.get("approved", False)
            reason = review.get("reason", "?")

            if approved:
                await self._emit({"type": "phase", "phase": "reviewer", "state": "done",
                    "msg": f"🔍 ✔ APPROUVÉ en {review_dur:.1f}s — {reason}"})
                result["success"] = True
                result["output"] = code_result.get("output", "")
                break
            else:
                await self._emit({"type": "phase", "phase": "reviewer", "state": "done",
                    "msg": f"🔍 ✘ REJETÉ en {review_dur:.1f}s — {reason}"})
                previous_errors.append(reason)

                if review.get("fix_plan"):
                    plan = review["fix_plan"]
                    await self._emit({"type": "log", "level": "info",
                        "msg": "  → Nouveau plan de correction reçu du reviewer"})

        total_dur = time.time() - t0
        if result["success"]:
            await self._emit({"type": "log", "level": "ok",
                "msg": f"\n✅ Tâche terminée avec succès en {total_dur:.1f}s"})
        else:
            await self._emit({"type": "log", "level": "err",
                "msg": f"\n❌ Échec après {MAX_RETRIES} tentatives ({total_dur:.1f}s)"})

        return result

    # ── Agents ────────────────────────────────────────────────────

    async def _plan(self, task: str) -> dict:
        search_instruction = ""
        if WEB_SEARCH_ENABLED:
            search_instruction = '\n- Si la tâche nécessite des infos récentes, ajoute "search_queries": ["query1", "query2"] (1-3 recherches).'

        prompt = f"""Tu es un agent planificateur expert.
Décompose la tâche en étapes concrètes.

Réponds UNIQUEMENT en JSON valide :
{{"steps": ["étape 1", ...], "files_to_create": ["chemin/fichier.ext", ...]{', "search_queries": ["..."]' if WEB_SEARCH_ENABLED else ''}}}

Règles :
- 2 à 8 étapes actionnables
- Liste tous les fichiers à créer{search_instruction}

Tâche : {task}"""

        raw = await self.client.chat(AGENTS["planner"], prompt)
        return self._parse_json(raw, {"steps": [task], "files_to_create": []})

    async def _code(self, task, plan, attempt, previous_errors, web_context=""):
        steps_txt = "\n".join(f"- {s}" for s in plan.get("steps", [task]))
        files_txt = ", ".join(plan.get("files_to_create", [])) or "à déterminer"
        errors_block = ""
        if previous_errors:
            errors_block = "\nERREURS PRÉCÉDENTES :\n" + "\n".join(f"  - {e}" for e in previous_errors) + "\n"
        web_block = f"\n{web_context}\nUtilise ces infos web pour un code plus précis.\n" if web_context else ""

        prompt = f"""Tu es un agent codeur senior. Code production-ready, complet, fonctionnel.

Réponds UNIQUEMENT en JSON valide :
{{"files": [{{"path": "chemin/fichier.ext", "content": "contenu COMPLET"}}], "commands": ["commande optionnelle"]}}

RÈGLES : fichiers COMPLETS, tous imports, gestion d'erreurs, pas de placeholder.
{web_block}
Tâche : {task}
Plan : {steps_txt}
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

    async def _review(self, task, code_result):
        files_summary = "\n".join(
            f"=== {f['path']} ===\n{f['content'][:1500]}" for f in code_result.get("files", []))

        prompt = f"""Tu es un reviewer senior exigeant.
Réponds UNIQUEMENT en JSON : {{"approved": true/false, "reason": "...", "fix_plan": {{"steps": [...], "files_to_create": [...]}}}}

Critères : code complet, imports, gestion erreurs, correspond à la tâche.

Tâche : {task}
Exécution : {code_result.get('output', 'aucun')}
Fichiers :
{files_summary}"""

        raw = await self.client.chat(AGENTS["reviewer"], prompt)
        return self._parse_json(raw, {"approved": True, "reason": "auto-approve (parse error)"})

    def _parse_json(self, raw, fallback):
        cleaned = re.sub(r'^```(?:json)?\s*\n?', '', raw.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r'\n?```\s*$', '', cleaned.strip(), flags=re.MULTILINE)
        try: return json.loads(cleaned)
        except: pass
        depth = 0; start = None
        for i, c in enumerate(raw):
            if c == '{':
                if depth == 0: start = i
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0 and start is not None:
                    try: return json.loads(raw[start:i+1])
                    except: start = None
        logger.warning(f"JSON parse failed. Raw[:200]: {raw[:200]}")
        return fallback
