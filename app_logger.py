"""Daily rotating file logging for the desktop assistant."""

from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from todo_store import data_file_path

APP_LOGGER_NAME = "desktop_assistant"
LOG_DIR_NAME = "logs"
LOG_FILE_NAME = "desktop_assistant.log"

_logger = logging.getLogger(APP_LOGGER_NAME)
_configured = False


def log_file_path() -> Path:
    return data_file_path().parent / LOG_DIR_NAME / LOG_FILE_NAME


def setup_logging(log_dir: Path | None = None) -> logging.Logger:
    """Configure the app logger once. Logs roll over at midnight."""
    global _configured
    if _configured:
        return _logger
    _logger.setLevel(logging.INFO)
    target_dir = log_dir or log_file_path().parent
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        handler = TimedRotatingFileHandler(
            target_dir / LOG_FILE_NAME,
            when="midnight",
            interval=1,
            backupCount=14,
            encoding="utf-8",
        )
        handler.suffix = "%Y-%m-%d"
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        _logger.addHandler(handler)
    except OSError:
        _logger.addHandler(logging.NullHandler())
    _configured = True
    return _logger
