"""Logging helpers to configure console and rotating file handlers."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterable

from app.config import get_settings

_CONFIGURED = False


def _resolve_level(level_name: str) -> int:
    try:
        return int(level_name)
    except (TypeError, ValueError):
        return getattr(logging, str(level_name or "INFO").upper(), logging.INFO)


def _has_file_handler(handlers: Iterable[logging.Handler], path: Path) -> bool:
    for handler in handlers:
        if isinstance(handler, RotatingFileHandler):
            if Path(getattr(handler, "baseFilename", "")) == path:
                return True
    return False


def setup_logging(force: bool = False) -> None:
    """Configure root logging with stream + rotating file handlers."""

    global _CONFIGURED  # noqa: PLW0603
    if _CONFIGURED and not force:
        return

    settings = get_settings()
    level = _resolve_level(settings.log_level)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Ensure there is at least one console handler for CLI contexts.
    if not any(isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler)
               for handler in root_logger.handlers):
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    log_dir = Path(settings.log_dir).expanduser().resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "seclens.log"

    if not _has_file_handler(root_logger.handlers, log_file):
        file_handler = RotatingFileHandler(
            str(log_file),
            maxBytes=int(settings.log_max_bytes),
            backupCount=int(settings.log_backup_count),
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # Make uvicorn loggers inherit the same handlers/levels but keep access logs readable.
    uvicorn_loggers = ["uvicorn", "uvicorn.error", "uvicorn.access"]
    for logger_name in uvicorn_loggers:
        logger = logging.getLogger(logger_name)
        if not logger.handlers:
            logger.propagate = True
        if logger.level < level:
            logger.setLevel(level)

    _CONFIGURED = True


__all__ = ["setup_logging"]
