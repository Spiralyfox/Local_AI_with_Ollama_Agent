#!/usr/bin/env python3
"""
Mode CLI — lance une tâche directement depuis le terminal.
Usage: python cli.py "Crée un serveur HTTP Python basique"
"""
import asyncio
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core import Orchestrator

WORKSPACE = Path.home() / "ai-workspace"

GREEN  = "\033[92m"
AMBER  = "\033[93m"
RED    = "\033[91m"
BLUE   = "\033[94m"
MUTED  = "\033[90m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


async def main(task: str, verbose: bool):
    orch = Orchestrator(WORKSPACE)

    print(f"\n{BOLD}{BLUE}▶ Tâche :{RESET} {task}")
    print(f"{MUTED}Workspace : {WORKSPACE}{RESET}\n")

    result = await orch.run(task)

    # Plan
    plan = result.get("plan", {})
    if plan.get("steps"):
        print(f"{BLUE}Plan :{RESET}")
        for s in plan["steps"]:
            print(f"  · {s}")
        print()

    # Étapes
    for step in result.get("steps", []):
        attempt = step.get("attempt", "?")
        code    = step.get("code", {})
        review  = step.get("review", {})

        print(f"{MUTED}── Tentative {attempt} ──{RESET}")
        for f in code.get("files", []):
            print(f"  {GREEN}✎{RESET} {f.get('path', '?')}")

        if verbose and code.get("output"):
            for line in code["output"].split("\n"):
                color = RED if line.startswith("ERR") else MUTED
                print(f"  {color}{line}{RESET}")

        if review:
            icon  = f"{GREEN}✔{RESET}" if review.get("approved") else f"{RED}✘{RESET}"
            label = "approuvé" if review.get("approved") else f"rejeté — {review.get('reason','?')}"
            print(f"  Review : {icon} {label}")
        print()

    # Résultat final
    if result.get("success"):
        print(f"{GREEN}{BOLD}✅ Terminé avec succès.{RESET}")
    else:
        print(f"{RED}{BOLD}❌ Échec après toutes les tentatives.{RESET}")

    # Fichiers créés
    files = orch.sandbox.list_files()
    if files:
        print(f"\n{BLUE}Fichiers dans le workspace :{RESET}")
        for f in files:
            print(f"  {MUTED}{f}{RESET}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Local AI System — CLI")
    parser.add_argument("task", nargs="?", help="Tâche à exécuter")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    task = args.task or input("Tâche : ").strip()
    if not task:
        print("Aucune tâche fournie.", file=sys.stderr)
        sys.exit(1)

    asyncio.run(main(task, args.verbose))
