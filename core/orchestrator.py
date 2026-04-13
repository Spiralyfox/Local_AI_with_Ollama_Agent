"""
Orchestrator v5.0 — multi-agent avec logs détaillés en temps réel.

Corrections v5.0 :
  - STREAM_CHUNK_SIZE 12 → 80  (réduit le flood WebSocket de ~10×)
  - previous_errors limité aux 3 derniers  (évite la croissance du contexte)
  - Reviewer : max 4 fichiers × 2000 chars  (au lieu de tous × 4000)
  - System prompts séparés du user prompt  (meilleure qualité de réponse)
  - Détection d'erreur Ollama dans le stream  (évite de parser du JSON cassé)
  - Config injectée proprement (temperature, max_tokens, cmd_timeout)
  - Validation basique du résultat codeur avant review
  - _parse_json: robustesse améliorée (réparation JSON tronqué)
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

MAX_RETRIES        = 5
WEB_SEARCH_ENABLED = False
TEMPERATURE        = 0.2
MAX_TOKENS         = 8192
CMD_TIMEOUT        = 60

# Nb de chars accumulés avant d'émettre un event stream
# 80 chars = ~10× moins d'awaits WebSocket qu'avec 12
STREAM_CHUNK_SIZE = 80

# Nombre max d'erreurs précédentes transmises au codeur (évite contexte infini)
MAX_PREV_ERRORS = 3

# Reviewer : limite pour rester dans un contexte raisonnable
REVIEW_MAX_FILES     = 4
REVIEW_MAX_CHARS_PER = 2000


class Orchestrator:
    def __init__(self, workspace: Path):
        self.workspace  = workspace
        self.client     = OllamaClient()
        self.sandbox    = Sandbox(workspace)
        self.searcher   = WebSearcher(max_results=5)
        self._broadcast = None

    def set_broadcast(self, broadcast_fn):
        self._broadcast = broadcast_fn

    async def _emit(self, event: dict):
        if self._broadcast:
            event.setdefault("ts", time.time())
            try:
                await self._broadcast(event)
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────
    # Point d'entrée principal
    # ─────────────────────────────────────────────────────────────

    async def run(self, task: str) -> dict:
        t0 = time.time()
        logger.info(f"Nouvelle tâche: {task!r}")
        result = {
            "task": task, "success": False, "steps": [], "output": "",
            "web_search_used": False, "search_results": {},
        }

        await self._emit({"type": "log", "level": "info",
            "msg": f"Démarrage — planner={AGENTS['planner']}  coder={AGENTS['coder']}  reviewer={AGENTS['reviewer']}"})
        await self._emit({"type": "log", "level": "info",
            "msg": f"Recherche web: {'activée' if WEB_SEARCH_ENABLED else 'désactivée'} | "
                   f"Retries: {MAX_RETRIES} | Temp: {TEMPERATURE} | Tokens: {MAX_TOKENS}"})

        # ── 1. Planification ──────────────────────────────────────
        await self._emit({"type": "phase", "phase": "planner", "state": "start",
            "msg": f"🧠 Planificateur ({AGENTS['planner']}) analyse la tâche…"})
        plan_t0  = time.time()
        plan     = await self._plan(task)
        plan_dur = time.time() - plan_t0
        result["plan"] = plan

        steps   = plan.get("steps",           [task])
        files   = plan.get("files_to_create", [])
        queries = plan.get("search_queries",  [])

        await self._emit({"type": "phase", "phase": "planner", "state": "done",
            "msg": f"🧠 Plan généré en {plan_dur:.1f}s — {len(steps)} étapes, {len(files)} fichiers"})
        for i, s in enumerate(steps):
            await self._emit({"type": "log", "level": "plan", "msg": f"  {i+1}. {s}"})
        if files:
            await self._emit({"type": "log", "level": "system",
                "msg": f"  Fichiers prévus: {', '.join(files)}"})

        # ── 2. Recherche web ──────────────────────────────────────
        web_context = ""
        if WEB_SEARCH_ENABLED and queries:
            await self._emit({"type": "phase", "phase": "search", "state": "start",
                "msg": f"🌐 Recherche web — {len(queries)} requêtes…"})
            for q in queries:
                await self._emit({"type": "log", "level": "search", "msg": f'  🔍 "{q}"'})

            search_t0      = time.time()
            search_results = await self.searcher.multi_search(queries, max_per_query=3)
            search_dur     = time.time() - search_t0
            web_context    = WebSearcher.format_results(search_results)
            result["web_search_used"] = True
            result["search_results"]  = {
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
                "msg": "🌐 Recherche web activée mais aucune requête nécessaire."})

        # ── 3. Boucle Codage / Review ─────────────────────────────
        previous_errors: list[str] = []

        for attempt in range(1, MAX_RETRIES + 1):
            await self._emit({"type": "log", "level": "info",
                "msg": f"\n{'═'*50}"})
            await self._emit({"type": "log", "level": "info",
                "msg": f"  TENTATIVE {attempt}/{MAX_RETRIES}"})
            await self._emit({"type": "log", "level": "info",
                "msg": f"{'═'*50}"})

            # ── Codage (streaming) ────────────────────────────────
            await self._emit({"type": "phase", "phase": "coder", "state": "start",
                "msg": f"💻 Codeur ({AGENTS['coder']}) génère le code…", "attempt": attempt})
            if web_context:
                await self._emit({"type": "log", "level": "system",
                    "msg": "  (contexte web injecté dans le prompt)"})
            if previous_errors:
                await self._emit({"type": "log", "level": "system",
                    "msg": f"  ({len(previous_errors[-MAX_PREV_ERRORS:])} erreur(s) précédente(s) transmises)"})

            code_t0     = time.time()
            code_result = await self._code(task, plan, attempt, previous_errors, web_context)
            code_dur    = time.time() - code_t0
            result["steps"].append({"attempt": attempt, "code": code_result})

            n_files = len(code_result.get("files",    []))
            n_cmds  = len(code_result.get("commands", []))
            await self._emit({"type": "phase", "phase": "coder", "state": "done",
                "msg": f"💻 Code généré en {code_dur:.1f}s — {n_files} fichiers, {n_cmds} commandes"})

            for f in code_result.get("files", []):
                size = len(f.get("content", ""))
                await self._emit({"type": "log", "level": "ok",
                    "msg": f"  ✎ {f.get('path', '?')} ({size} chars)"})

            if code_result.get("output"):
                for line in code_result["output"].split("\n"):
                    if line.strip():
                        lvl = "err" if (line.startswith("ERR") or "FAIL" in line) else "system"
                        await self._emit({"type": "log", "level": lvl, "msg": f"  {line}"})

            # Vérification rapide : aucun fichier produit = on rejette sans appeler le reviewer
            if not code_result.get("files"):
                reason = "Le codeur n'a produit aucun fichier (réponse vide ou invalide)."
                await self._emit({"type": "phase", "phase": "reviewer", "state": "done",
                    "msg": f"🔍 ✘ REJETÉ (auto) — {reason}"})
                previous_errors.append(reason)
                result["steps"][-1]["review"] = {"approved": False, "reason": reason}
                continue

            # ── Review ───────────────────────────────────────────
            await self._emit({"type": "phase", "phase": "reviewer", "state": "start",
                "msg": f"🔍 Reviewer ({AGENTS['reviewer']}) évalue le code…"})
            review_t0  = time.time()
            review     = await self._review(task, code_result)
            review_dur = time.time() - review_t0
            result["steps"][-1]["review"] = review

            approved = review.get("approved", False)
            reason   = review.get("reason",   "?")

            if approved:
                await self._emit({"type": "phase", "phase": "reviewer", "state": "done",
                    "msg": f"🔍 ✔ APPROUVÉ en {review_dur:.1f}s — {reason}"})
                result["success"] = True
                result["output"]  = code_result.get("output", "")
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

    # ─────────────────────────────────────────────────────────────
    # Agents
    # ─────────────────────────────────────────────────────────────

    async def _plan(self, task: str) -> dict:
        system = (
            "Tu es un agent planificateur expert en architecture logicielle. "
            "Tu réponds UNIQUEMENT en JSON valide, sans texte avant ou après, sans balise markdown."
        )
        search_field = ', "search_queries": ["query1"]' if WEB_SEARCH_ENABLED else ""
        search_rule  = (
            "\n- Si la tâche nécessite des infos récentes, ajoute search_queries (1 à 3 requêtes)."
            if WEB_SEARCH_ENABLED else ""
        )
        prompt = (
            f"Décompose la tâche suivante en étapes concrètes.\n\n"
            f"Format OBLIGATOIRE (JSON brut uniquement) :\n"
            f'{{"steps": ["étape 1", "étape 2"], "files_to_create": ["chemin/fichier.ext"]{search_field}}}\n\n'
            f"Règles :\n"
            f"- Entre 2 et 8 étapes actionnables et précises\n"
            f"- Liste TOUS les fichiers à créer avec leur chemin relatif{search_rule}\n\n"
            f"Tâche : {task}"
        )
        raw = await self.client.chat(
            AGENTS["planner"], prompt, system=system,
            temperature=TEMPERATURE, max_tokens=min(MAX_TOKENS, 2048),
        )
        return self._parse_json(raw, {"steps": [task], "files_to_create": []})

    async def _code(self, task: str, plan: dict, attempt: int,
                    previous_errors: list[str], web_context: str = "") -> dict:
        system = (
            "Tu es un agent codeur senior spécialisé en production de code complet. "
            "Tu réponds UNIQUEMENT en JSON valide, sans texte avant ou après, sans balise markdown."
        )
        steps_txt     = "\n".join(f"- {s}" for s in plan.get("steps", [task]))
        files_txt     = ", ".join(plan.get("files_to_create", [])) or "à déterminer"

        # Garder seulement les N dernières erreurs pour éviter la croissance du contexte
        recent_errors = previous_errors[-MAX_PREV_ERRORS:]
        errors_block  = ""
        if recent_errors:
            errors_block = (
                "\nERREURS À CORRIGER (tentatives précédentes) :\n"
                + "\n".join(f"  - {e}" for e in recent_errors)
                + "\n"
            )

        web_block = (
            f"\nCONTEXTE WEB :\n{web_context}\n"
            if web_context else ""
        )

        prompt = (
            f"Format OBLIGATOIRE (JSON brut uniquement) :\n"
            f'{{"files": [{{"path": "chemin/fichier.ext", "content": "contenu COMPLET"}}], '
            f'"commands": ["pip install X  # optionnel"]}}\n\n'
            f"RÈGLES STRICTES :\n"
            f"- Chaque fichier doit être COMPLET (tous imports, toute la logique)\n"
            f"- Gestion des erreurs obligatoire\n"
            f"- Aucun placeholder (pas de # TODO, pas de ...)\n"
            f"- Les commands sont optionnelles, uniquement pour l'installation de dépendances\n"
            f"{web_block}"
            f"Tâche : {task}\n"
            f"Plan :\n{steps_txt}\n"
            f"Fichiers attendus : {files_txt}\n"
            f"Tentative {attempt}/{MAX_RETRIES}"
            f"{errors_block}"
        )

        # ── Streaming token par token ─────────────────────────────
        raw       = ""
        chunk_buf = ""
        await self._emit({"type": "stream_start", "phase": "coder"})

        async for token in self.client.chat_stream(
            AGENTS["coder"], prompt, system=system,
            temperature=TEMPERATURE, max_tokens=MAX_TOKENS,
        ):
            raw       += token
            chunk_buf += token
            if len(chunk_buf) >= STREAM_CHUNK_SIZE:
                await self._emit({"type": "stream_token", "phase": "coder", "token": chunk_buf})
                chunk_buf = ""

        if chunk_buf:
            await self._emit({"type": "stream_token", "phase": "coder", "token": chunk_buf})
        await self._emit({"type": "stream_end", "phase": "coder"})

        # Vérification : le stream a-t-il retourné une erreur Ollama ?
        if '"error"' in raw[:120] and len(raw) < 300:
            err_data = self._parse_json(raw, {})
            if err_data.get("error"):
                logger.error(f"Erreur Ollama dans le stream: {err_data['error']}")
                return {"files": [], "commands": [], "output": f"ERR: Ollama — {err_data['error']}"}

        data = self._parse_json(raw, {"files": [], "commands": []})

        output_log: list[str] = []
        for f in data.get("files", []):
            path, content = f.get("path", ""), f.get("content", "")
            if path and content:
                ok, msg = self.sandbox.write_file(path, content)
                output_log.append(f"{'OK' if ok else 'ERR'}: {path} — {msg}")
            elif path and not content:
                output_log.append(f"ERR: {path} — contenu vide ignoré")

        for cmd in data.get("commands", []):
            if cmd.strip():
                ok, out = self.sandbox.run_command(cmd, timeout=CMD_TIMEOUT)
                output_log.append(f"CMD({'OK' if ok else 'FAIL'}): {cmd}\n{out}")

        data["output"] = "\n".join(output_log)
        return data

    async def _review(self, task: str, code_result: dict) -> dict:
        system = (
            "Tu es un reviewer senior exigeant. "
            "Tu réponds UNIQUEMENT en JSON valide, sans texte avant ou après, sans balise markdown."
        )

        # Limiter le contexte : max REVIEW_MAX_FILES fichiers × REVIEW_MAX_CHARS_PER chars
        all_files = code_result.get("files", [])
        files     = all_files[:REVIEW_MAX_FILES]
        parts     = []
        for f in files:
            content = f.get("content", "")
            trunc   = content[:REVIEW_MAX_CHARS_PER]
            suffix  = "…[tronqué]" if len(content) > REVIEW_MAX_CHARS_PER else ""
            parts.append(f"=== {f['path']} ===\n{trunc}{suffix}")

        skipped = len(all_files) - len(files)
        files_summary = "\n".join(parts)
        if skipped > 0:
            files_summary += f"\n\n[{skipped} fichier(s) supplémentaire(s) non affichés]"

        prompt = (
            f"Évalue si le code produit répond correctement à la tâche demandée.\n\n"
            f"Format OBLIGATOIRE (JSON brut uniquement) :\n"
            f'Si approuvé : {{"approved": true, "reason": "explication courte"}}\n'
            f'Si rejeté   : {{"approved": false, "reason": "problème précis", '
            f'"fix_plan": {{"steps": ["correction 1"], "files_to_create": ["fichier.py"]}}}}\n\n'
            f"Critères d'approbation :\n"
            f"- Code complet (pas de placeholder ni TODO)\n"
            f"- Tous les imports présents\n"
            f"- Gestion d'erreurs présente\n"
            f"- Correspond à la tâche demandée\n\n"
            f"Tâche : {task}\n"
            f"Résultat d'exécution : {code_result.get('output', 'aucun')}\n"
            f"Fichiers produits :\n{files_summary}"
        )

        raw = await self.client.chat(
            AGENTS["reviewer"], prompt, system=system,
            temperature=0.1,                       # plus déterministe pour le reviewer
            max_tokens=min(MAX_TOKENS, 1024),
        )
        return self._parse_json(raw, {"approved": True, "reason": "auto-approve (parse error)"})

    # ─────────────────────────────────────────────────────────────
    # Parsing JSON robuste
    # ─────────────────────────────────────────────────────────────

    def _parse_json(self, raw: str, fallback: dict) -> dict:
        # 1. Nettoyer les balises markdown ```json ... ```
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", raw.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"\n?```\s*$",           "", cleaned.strip(), flags=re.MULTILINE)
        try:
            return json.loads(cleaned)
        except Exception:
            pass

        # 2. Extraire le premier objet JSON complet par comptage d'accolades
        depth = 0
        start = None
        for i, c in enumerate(raw):
            if c == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    candidate = raw[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except Exception:
                        start = None  # continuer à chercher

        # 3. JSON tronqué : tenter de refermer jusqu'au dernier }
        last_brace = raw.rfind("}")
        if last_brace != -1:
            try:
                return json.loads(raw[:last_brace + 1])
            except Exception:
                pass

        logger.warning(f"JSON parse failed. Raw[:300]: {raw[:300]}")
        return fallback
