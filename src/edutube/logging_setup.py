"""Logging setup (LLD §10, LLR-LOG-01..03)."""

from __future__ import annotations

import contextlib
import logging
import re
from collections.abc import Iterator
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.logging import RichHandler

_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"

_SECRET_KEYS = (
    "pexels_api_key",
    "authorization",
    "access_token",
    "refresh_token",
    "client_secret",
)
_SECRET_PATTERN = re.compile(
    r"(?i)(" + "|".join(_SECRET_KEYS) + r")([\"']?\s*[:=]\s*[\"']?)([^\s\"',}]+)"
)


class RedactFilter(logging.Filter):
    """Masks values of known secret keys and Authorization headers (LLR-LOG-03)."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        redacted = _SECRET_PATTERN.sub(r"\1\2***REDACTED***", msg)
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


def setup_logging(logs_dir: Path, *, debug: bool = False) -> None:
    """Configure the root logger with a Rich console handler and rotating file handler."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("edutube")
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    root.handlers.clear()

    console = RichHandler(rich_tracebacks=True, show_path=False)
    console.setLevel(logging.DEBUG if debug else logging.INFO)
    console.addFilter(RedactFilter())

    file_handler = RotatingFileHandler(
        logs_dir / "edutube.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    file_handler.setLevel(logging.DEBUG)
    file_handler.addFilter(RedactFilter())

    root.addHandler(console)
    root.addHandler(file_handler)


@contextlib.contextmanager
def job_log_handler(job_log_path: Path) -> Iterator[None]:
    """Attach a per-job file handler for the duration of the context (LLR-LOG-02)."""
    job_log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(job_log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    handler.setLevel(logging.DEBUG)
    handler.addFilter(RedactFilter())
    root = logging.getLogger("edutube")
    root.addHandler(handler)
    try:
        yield
    finally:
        root.removeHandler(handler)
        handler.close()


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"edutube.{name}")
