"""
Sandbox — toutes les opérations fichiers/commandes sont confinées au workspace.
Jamais d'accès root, jamais hors du répertoire autorisé.
"""
import os
import subprocess
import shlex
from pathlib import Path
from .logger import get_logger

logger = get_logger("sandbox")

# Commandes totalement interdites
BANNED_COMMANDS = {
    "rm -rf /", "sudo", "su ", "chmod 777 /", "mkfs", "dd if=",
    "curl | sh", "wget | sh", "curl | bash", ">(", ">&", "/etc/passwd",
    "/etc/shadow", "shutdown", "reboot", "halt", "poweroff",
}

# Extensions autorisées à la création
ALLOWED_EXTENSIONS = {
    ".py", ".js", ".ts", ".html", ".css", ".json", ".yaml", ".yml",
    ".md", ".txt", ".sh", ".env.example", ".toml", ".cfg", ".ini",
    ".sql", ".graphql", ".rs", ".go", ".java", ".cpp", ".c", ".h",
}


class Sandbox:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        logger.info(f"Sandbox initialisée: {self.workspace}")

    # ------------------------------------------------------------------
    # Écriture de fichier
    # ------------------------------------------------------------------
    def write_file(self, relative_path: str, content: str) -> tuple[bool, str]:
        """Crée ou écrase un fichier dans le workspace."""
        target = self._resolve(relative_path)
        if target is None:
            return False, "Chemin hors sandbox refusé"

        ext = target.suffix.lower()
        if ext and ext not in ALLOWED_EXTENSIONS:
            return False, f"Extension non autorisée: {ext}"

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        logger.info(f"Fichier écrit: {target.relative_to(self.workspace)}")
        return True, f"Écrit ({len(content)} caractères)"

    def read_file(self, relative_path: str) -> tuple[bool, str]:
        target = self._resolve(relative_path)
        if target is None or not target.exists():
            return False, "Fichier introuvable ou hors sandbox"
        return True, target.read_text(encoding="utf-8")

    def list_files(self, subdir: str = "") -> list[str]:
        root = self._resolve(subdir) if subdir else self.workspace
        if root is None or not root.exists():
            return []
        return [
            str(p.relative_to(self.workspace))
            for p in root.rglob("*")
            if p.is_file()
        ]

    # ------------------------------------------------------------------
    # Exécution de commandes
    # ------------------------------------------------------------------
    def run_command(self, cmd: str, timeout: int = 30) -> tuple[bool, str]:
        """Exécute une commande shell dans le workspace, avec garde-fous."""
        # Vérification des commandes interdites
        cmd_lower = cmd.lower()
        for banned in BANNED_COMMANDS:
            if banned in cmd_lower:
                logger.warning(f"Commande interdite bloquée: {cmd!r}")
                return False, f"Commande refusée (sécurité): {banned}"

        # Jamais en root
        if os.geteuid() == 0:
            return False, "Exécution root refusée"

        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, "HOME": str(self.workspace)},
            )
            output = proc.stdout + proc.stderr
            success = proc.returncode == 0
            logger.info(f"CMD ({'OK' if success else f'RC={proc.returncode}'}): {cmd[:80]}")
            return success, output[:2000]   # limite de sortie
        except subprocess.TimeoutExpired:
            return False, f"Timeout ({timeout}s) dépassé"
        except Exception as e:
            return False, str(e)

    # ------------------------------------------------------------------
    # Interne
    # ------------------------------------------------------------------
    def _resolve(self, relative_path: str) -> Path | None:
        """Résout un chemin relatif et vérifie qu'il reste dans le workspace."""
        # Nettoyage défensif
        relative_path = relative_path.lstrip("/").replace("..", "")
        target = (self.workspace / relative_path).resolve()
        if not str(target).startswith(str(self.workspace)):
            logger.warning(f"Path traversal détecté: {relative_path!r}")
            return None
        return target
