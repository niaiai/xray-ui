from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .storage import default_data_dir


def configure_logging(log_dir: Path | None = None) -> logging.Logger:
    logger = logging.getLogger("xray_ui")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    directory = log_dir or default_data_dir() / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        directory / "xray-ui.log", maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger
