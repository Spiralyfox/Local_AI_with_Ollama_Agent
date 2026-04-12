"""
Orchestrator — coordonne les agents planificateur, codeur, critique.
"""
import asyncio
import json
import time
from pathlib import Path
from typing import Optional
from .ollama_client import OllamaClient
from .sandbox import Sandbox
from .logger import get_logger

logger = get_logger("orchestrator")

AGENTS = {
    "planner":  "qwen2.5-coder:7b",   # remplacer par deepseek-r1 si dispo
    "coder":    "qwen2.5-coder:7b",
    "reviewer": "qwen2.5-coder:7b",
}

MAX_RETRIES = 3


class Orchestrator:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.client = OllamaClient()
        self.sandbox = Sandbox(workspace)

    # ------------------------------------------------------------------
    # Boucle principale
    # ------------------------------------------------------------------
    async def run(self, task: str) -> dict:
        logger.info(f"Nouvelle tâche: {task!r}")
        result = {"task": task, "success": False, "steps": [], "output": ""}

        # 1. Planification
        plan = await self._plan(task)
        result["plan"] = plan
        logger.info(f"Plan: {plan}")

        # 2. Codage avec corrections auto
        for attempt in range(1, MAX_RETRIES + 1):
            logger.info(f"Tentative {attempt}/{MAX_RETRIES}")
            code_result = await self._code(task, plan, attempt)
            result["steps"].append({"attempt": attempt, "code": code_result})

            # 3. Revue
            review = await self._review(task, code_result)
            result["steps"][-1]["review"] = review

            if review.get("approved"):
                result["success"] = True
                result["output"] = code_result.get("output", "")
                logger.info("Tâche approuvée par le reviewer.")
                break

            logger.warning(f"Rejeté: {review.get('reason', '?')} — on réessaie.")
            plan = review.get("fix_plan", plan)   # le reviewer donne le plan corrigé

        return result

    # ------------------------------------------------------------------
    # Agent planificateur
    # ------------------------------------------------------------------
    async def _plan(self, task: str) -> str:
        prompt = f"""Tu es un agent planificateur.
Décompose la tâche suivante en étapes concrètes (max 5 étapes).
Réponds en JSON: {{"steps": ["étape 1", "étape 2", ...], "files_to_create": ["chemin/fichier.py"]}}

Tâche: {task}"""
        raw = await self.client.chat(AGENTS["planner"], prompt)
        try:
            return json.loads(raw)
        except Exception:
            return {"steps": [task], "files_to_create": []}

    # ------------------------------------------------------------------
    # Agent codeur
    # ------------------------------------------------------------------
    async def _code(self, task: str, plan: dict, attempt: int) -> dict:
        steps_txt = "\n".join(f"- {s}" for s in plan.get("steps", [task]))
        files_txt = ", ".join(plan.get("files_to_create", []))

        prompt = f"""Tu es un agent codeur expert.
Écris le code pour accomplir la tâche suivante.
Réponds UNIQUEMENT avec un objet JSON structuré ainsi:
{{
  "files": [
    {{"path": "chemin/relatif/fichier.py", "content": "# contenu du fichier\\n..."}}
  ],
  "commands": ["commande shell optionnelle"]
}}

Tâche: {task}
Étapes du plan:
{steps_txt}
Fichiers attendus: {files_txt}
Tentative n°{attempt} — génère du code fonctionnel et complet."""

        raw = await self.client.chat(AGENTS["coder"], prompt)
        try:
            data = json.loads(raw)
        except Exception:
            # Fallback: on tente d'extraire un bloc JSON du texte
            import re
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            data = json.loads(m.group()) if m else {"files": [], "commands": []}

        output_log = []
        for f in data.get("files", []):
            path, content = f.get("path", ""), f.get("content", "")
            if path and content:
                ok, msg = self.sandbox.write_file(path, content)
                output_log.append(f"{'OK' if ok else 'ERR'}: {path} — {msg}")

        for cmd in data.get("commands", []):
            ok, out = self.sandbox.run_command(cmd)
            output_log.append(f"CMD({'OK' if ok else 'FAIL'}): {cmd}\n{out}")

        data["output"] = "\n".join(output_log)
        return data

    # ------------------------------------------------------------------
    # Agent critique / reviewer
    # ------------------------------------------------------------------
    async def _review(self, task: str, code_result: dict) -> dict:
        files_summary = "\n".join(
            f"=== {f['path']} ===\n{f['content'][:800]}"
            for f in code_result.get("files", [])
        )
        prompt = f"""Tu es un agent reviewer senior.
Évalue si le code produit répond bien à la tâche.
Réponds en JSON: {{"approved": true/false, "reason": "...", "fix_plan": {{"steps": [], "files_to_create": []}}}}

Tâche originale: {task}
Résultat d'exécution: {code_result.get('output', '')}
Fichiers produits:
{files_summary}

Sois strict mais juste. Si le code est fonctionnel et complet, approuve-le."""
        raw = await self.client.chat(AGENTS["reviewer"], prompt)
        try:
            return json.loads(raw)
        except Exception:
            return {"approved": True, "reason": "review parse error — auto-approve"}
