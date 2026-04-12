"""Logger centralisé."""
import logging
import sys
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(f"ai.{name}")
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
            datefmt="%H:%M:%S",
        )
        # Console
        sh = logging.StreamHandler(sys.stdout)
        sh.setLevel(logging.INFO)
        sh.setFormatter(fmt)
        logger.addHandler(sh)
        # Fichier
        fh = logging.FileHandler(LOG_DIR / "agent.log", encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger
