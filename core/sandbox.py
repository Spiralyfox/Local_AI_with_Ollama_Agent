"""
Sandbox v5.0 — opérations fichiers/commandes confinées au workspace.

Corrections v5.0 :
  - Import shlex inutilisé supprimé
  - Sanitisation de chemin renforcée (double check après resolve)
  - max_file_size_kb configurable (défaut 2048 KB)
  - run_command : timeout passé en paramètre (synchronisé avec la config)
  - list_files : tri alphabétique pour un affichage stable
"""
import os
import subprocess
from pathlib import Path
from .logger import get_logger

logger = get_logger("sandbox")

# Commandes totalement interdites (vérification lowercase)
BANNED_COMMANDS: frozenset[str] = frozenset({
    "rm -rf /", "sudo", "su ", "chmod 777 /", "mkfs", "dd if=",
    "curl | sh", "wget | sh", "curl | bash", ">(", ">&",
    "/etc/passwd", "/etc/shadow",
    "shutdown", "reboot", "halt", "poweroff",
})

# Extensions autorisées à la création
ALLOWED_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".html", ".css", ".scss",
    ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini",
    ".md", ".txt", ".rst",
    ".sh", ".bash",
    ".env.example",
    ".sql", ".graphql",
    ".rs", ".go", ".java", ".cpp", ".c", ".h", ".cs",
    ".rb", ".php", ".swift", ".kt",
    ".xml", ".svg",
})

# Taille max par fichier (modifiable via set_max_file_size)
DEFAULT_MAX_FILE_SIZE_KB = 2048


class Sandbox:
    def __init__(self, workspace: Path, max_file_size_kb: int = DEFAULT_MAX_FILE_SIZE_KB):
        self.workspace        = workspace.resolve()
        self.max_file_size_kb = max_file_size_kb
        self.workspace.mkdir(parents=True, exist_ok=True)
        logger.info(f"Sandbox initialisée: {self.workspace}  (max_file: {max_file_size_kb} KB)")

    # ------------------------------------------------------------------
    # Configuration runtime
    # ------------------------------------------------------------------

    def set_max_file_size(self, kb: int):
        self.max_file_size_kb = max(64, kb)

    # ------------------------------------------------------------------
    # Fichiers
    # ------------------------------------------------------------------

    def write_file(self, relative_path: str, content: str) -> tuple[bool, str]:
        """Crée ou écrase un fichier dans le workspace."""
        target = self._resolve(relative_path)
        if target is None:
            return False, "Chemin hors sandbox refusé"

        # Vérification extension
        ext = target.suffix.lower()
        if ext and ext not in ALLOWED_EXTENSIONS:
            return False, f"Extension non autorisée: {ext}"

        # Vérification taille
        size_kb = len(content.encode("utf-8")) / 1024
        if size_kb > self.max_file_size_kb:
            return False, (
                f"Fichier trop volumineux: {size_kb:.0f} KB > {self.max_file_size_kb} KB"
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        logger.info(f"Fichier écrit: {target.relative_to(self.workspace)} ({size_kb:.1f} KB)")
        return True, f"Écrit ({len(content)} chars, {size_kb:.1f} KB)"

    def read_file(self, relative_path: str) -> tuple[bool, str]:
        target = self._resolve(relative_path)
        if target is None or not target.exists():
            return False, "Fichier introuvable ou hors sandbox"
        try:
            return True, target.read_text(encoding="utf-8")
        except Exception as e:
            return False, f"Erreur de lecture: {e}"

    def list_files(self, subdir: str = "") -> list[str]:
        root = self._resolve(subdir) if subdir else self.workspace
        if root is None or not root.exists():
            return []
        files = [
            str(p.relative_to(self.workspace))
            for p in root.rglob("*")
            if p.is_file()
        ]
        return sorted(files)

    # ------------------------------------------------------------------
    # Commandes
    # ------------------------------------------------------------------

    def run_command(self, cmd: str, timeout: int = 30) -> tuple[bool, str]:
        """Exécute une commande shell dans le workspace, avec garde-fous."""
        cmd_stripped = cmd.strip()
        if not cmd_stripped:
            return False, "Commande vide"

        # Vérification des commandes interdites
        cmd_lower = cmd_stripped.lower()
        for banned in BANNED_COMMANDS:
            if banned in cmd_lower:
                logger.warning(f"Commande interdite bloquée: {cmd!r}")
                return False, f"Commande refusée (sécurité): '{banned}'"

        # Jamais en root
        if os.geteuid() == 0:
            return False, "Exécution root refusée"

        try:
            proc = subprocess.run(
                cmd_stripped,
                shell=True,
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, "HOME": str(self.workspace)},
            )
            output  = (proc.stdout + proc.stderr).strip()
            success = proc.returncode == 0
            logger.info(
                f"CMD ({'OK' if success else f'RC={proc.returncode}'}): {cmd_stripped[:80]}"
            )
            # Limiter la sortie retournée
            if len(output) > 3000:
                output = output[:3000] + "\n…[sortie tronquée]"
            return success, output
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
        cleaned = (
            relative_path
            .strip()
            .lstrip("/\\")
            .replace("..", "")
            .replace("~", "")
        )
        if not cleaned:
            return None

        target = (self.workspace / cleaned).resolve()

        # Double vérification : le chemin résolu est bien sous le workspace
        try:
            target.relative_to(self.workspace)
        except ValueError:
            logger.warning(f"Path traversal détecté: {relative_path!r} → {target}")
            return None

        return target
