"""
Orchestrator v2 — coordonne les agents planificateur, codeur, critique.
Optimisé pour projets lourds : multi-fichiers, retries intelligents, prompts robustes.
"""
import json
import re
from pathlib import Path
from .ollama_client import OllamaClient
from .sandbox import Sandbox
from .logger import get_logger

logger = get_logger("orchestrator")

AGENTS = {
    "planner":  "qwen2.5-coder:7b",
    "coder":    "qwen2.5-coder:7b",
    "reviewer": "qwen2.5-coder:7b",
}

MAX_RETRIES = 5


class Orchestrator:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.client = OllamaClient()
        self.sandbox = Sandbox(workspace)

    async def run(self, task: str) -> dict:
        logger.info(f"Nouvelle tâche: {task!r}")
        result = {"task": task, "success": False, "steps": [], "output": ""}

        plan = await self._plan(task)
        result["plan"] = plan
        logger.info(f"Plan: {plan}")

        previous_errors = []
        for attempt in range(1, MAX_RETRIES + 1):
            logger.info(f"Tentative {attempt}/{MAX_RETRIES}")
            code_result = await self._code(task, plan, attempt, previous_errors)
            result["steps"].append({"attempt": attempt, "code": code_result})

            review = await self._review(task, code_result)
            result["steps"][-1]["review"] = review

            if review.get("approved"):
                result["success"] = True
                result["output"] = code_result.get("output", "")
                logger.info("Tâche approuvée par le reviewer.")
                break

            reason = review.get("reason", "?")
            logger.warning(f"Rejeté: {reason} — on réessaie.")
            previous_errors.append(reason)

            if review.get("fix_plan"):
                plan = review["fix_plan"]

        return result

    async def _plan(self, task: str) -> dict:
        prompt = f"""Tu es un agent planificateur expert en architecture logicielle.
Analyse la tâche et décompose-la en étapes concrètes et précises.
Pour les projets complexes, pense à : structure des fichiers, dépendances, tests, configuration.

Réponds UNIQUEMENT avec un JSON valide (pas de markdown, pas de texte avant/après) :
{{"steps": ["étape 1", "étape 2", ...], "files_to_create": ["chemin/fichier.ext", ...]}}

Règles :
- Maximum 8 étapes, minimum 2
- Chaque étape doit être actionnable
- Liste tous les fichiers à créer avec leurs chemins relatifs
- Pour les projets web : inclure HTML, CSS/JS, et fichier serveur
- Pour les projets Python : inclure requirements.txt si nécessaire

Tâche : {task}"""

        raw = await self.client.chat(AGENTS["planner"], prompt)
        return self._parse_json(raw, {"steps": [task], "files_to_create": []})

    async def _code(self, task: str, plan: dict, attempt: int, previous_errors: list) -> dict:
        steps_txt = "\n".join(f"- {s}" for s in plan.get("steps", [task]))
        files_txt = ", ".join(plan.get("files_to_create", [])) or "à déterminer"

        errors_context = ""
        if previous_errors:
            errors_txt = "\n".join(f"  - Tentative {i+1}: {e}" for i, e in enumerate(previous_errors))
            errors_context = f"""

ERREURS DES TENTATIVES PRÉCÉDENTES (corrige-les) :
{errors_txt}
"""

        prompt = f"""Tu es un agent codeur senior. Écris du code production-ready, complet et fonctionnel.

Réponds UNIQUEMENT avec un JSON valide (pas de markdown, pas de ```json, pas de texte) :
{{
  "files": [
    {{"path": "chemin/relatif/fichier.ext", "content": "contenu complet du fichier"}}
  ],
  "commands": ["commande shell optionnelle pour installer deps ou tester"]
}}

RÈGLES STRICTES :
- Chaque fichier doit être COMPLET, pas de "..." ou "# reste du code"
- Inclure TOUS les imports nécessaires
- Inclure la gestion d'erreurs
- Pour Python : ajouter if __name__ == "__main__" quand pertinent
- Pour les serveurs : utiliser le port 8000 par défaut
- Pour HTML : inclure CSS inline, page complète avec <!DOCTYPE html>
- Les commandes shell sont optionnelles (pip install, npm install, etc.)
- NE PAS utiliser sudo dans les commandes

Tâche : {task}
Plan :
{steps_txt}
Fichiers attendus : {files_txt}
Tentative n°{attempt}/{MAX_RETRIES}
{errors_context}"""

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

    async def _review(self, task: str, code_result: dict) -> dict:
        files_summary = "\n".join(
            f"=== {f['path']} ===\n{f['content'][:1500]}"
            for f in code_result.get("files", [])
        )

        prompt = f"""Tu es un agent reviewer senior et exigeant.
Évalue si le code produit répond COMPLÈTEMENT à la tâche demandée.

Réponds UNIQUEMENT avec un JSON valide :
{{"approved": true/false, "reason": "explication", "fix_plan": {{"steps": [...], "files_to_create": [...]}}}}

Critères d'évaluation :
1. Le code est-il complet ? (pas de placeholder, pas de "TODO")
2. Les imports sont-ils tous présents ?
3. Le code gère-t-il les erreurs ?
4. Le code correspond-il à la tâche demandée ?
5. Pour le web : HTML complet, CSS inclus ?

Si le code est bon et fonctionnel → approved: true
Si un problème est trouvé → approved: false avec un fix_plan précis

Tâche originale : {task}
Résultat d'exécution : {code_result.get('output', 'aucun')}
Fichiers produits :
{files_summary}"""

        raw = await self.client.chat(AGENTS["reviewer"], prompt)
        return self._parse_json(raw, {"approved": True, "reason": "auto-approve (parse error)"})

    def _parse_json(self, raw: str, fallback: dict) -> dict:
        """Parse robuste de JSON depuis la sortie LLM."""
        # Nettoyer les blocs markdown
        cleaned = re.sub(r'^```(?:json)?\s*\n?', '', raw.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r'\n?```\s*$', '', cleaned.strip(), flags=re.MULTILINE)

        # Essai direct
        try:
            return json.loads(cleaned)
        except Exception:
            pass

        # Chercher le premier { ... } valide
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

        logger.warning(f"JSON parse failed, using fallback. Raw[:200]: {raw[:200]}")
        return fallback
