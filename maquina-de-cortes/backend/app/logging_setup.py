from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .config import get_settings


def setup_logging(name: str) -> None:
    s = get_settings()
    handler = RotatingFileHandler(s.data_dir / "logs" / f"{name}.log", maxBytes=5_000_000,
                                  backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(s.log_level)
    root.addHandler(handler)
