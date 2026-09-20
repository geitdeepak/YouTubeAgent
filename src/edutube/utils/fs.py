"""Filesystem helpers: atomic write, job lock file, cross-platform file open."""

from __future__ import annotations

import contextlib
import os
import platform
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

STALE_LOCK_SECONDS = 2 * 60 * 60  # LLR-ORC-05


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write text to ``path`` atomically via a temp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    tmp.write_text(content, encoding=encoding)
    tmp.replace(path)


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    tmp.write_bytes(content)
    tmp.replace(path)


@contextlib.contextmanager
def job_lock(job_dir: Path) -> Iterator[None]:
    """Prevent concurrent runs of the same job (LLR-ORC-05)."""
    job_dir.mkdir(parents=True, exist_ok=True)
    lock_path = job_dir / ".lock"
    if lock_path.exists():
        age = time.time() - lock_path.stat().st_mtime
        if age > STALE_LOCK_SECONDS:
            lock_path.unlink(missing_ok=True)
        else:
            raise RuntimeError(f"Job is locked (another run in progress?): {lock_path}")
    lock_path.write_text(str(os.getpid()), encoding="utf-8")
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def open_file(path: Path) -> None:
    """Open a file with the OS default application (LLR-CLI-06)."""
    system = platform.system()
    if system == "Windows":
        os.startfile(str(path))
    elif system == "Darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


def set_owner_only_permissions(path: Path) -> None:
    """chmod 600 on POSIX; no-op on Windows (LLR-AUT-03)."""
    if sys.platform != "win32":
        os.chmod(path, 0o600)
