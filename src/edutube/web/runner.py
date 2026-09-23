"""Background execution of pipeline jobs for the web UI.

The web server handles HTTP requests synchronously and quickly; actual video
generation/upload (which can take minutes) runs on a small thread pool so
requests never block. Each background task opens its own `Repository` (its
own SQLite connection) since sqlite3 connections are not safe to share across
threads. `_RUNNING` is purely a UI convenience (spinner / disabled buttons) --
job status itself always comes from the database, which remains the source
of truth even if the server restarts mid-job.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from edutube.config import AppConfig, Secrets
from edutube.db import Repository
from edutube.errors import EdutubeError
from edutube.logging_setup import get_logger
from edutube.pipeline import orchestrator
from edutube.pipeline.stages import UploadStage

log = get_logger("web.runner")

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="edutube-job")
_RUNNING: set[str] = set()
_LOCK = threading.Lock()


def is_running(job_id: str) -> bool:
    with _LOCK:
        return job_id in _RUNNING


def _mark_running(job_id: str) -> None:
    with _LOCK:
        _RUNNING.add(job_id)


def _mark_done(job_id: str) -> None:
    with _LOCK:
        _RUNNING.discard(job_id)


def submit_job(cfg: AppConfig, secrets: Secrets, job_id: str) -> None:
    """Run the pipeline for `job_id` on a background thread."""
    _mark_running(job_id)

    def _run() -> None:
        try:
            repo = Repository(cfg.resolve(cfg.paths.db))
            try:
                orchestrator.run_job(job_id, cfg, secrets, repo)
            finally:
                repo.close()
        except EdutubeError as e:
            log.warning("background job %s failed: %s", job_id, e)
        except Exception:  # noqa: BLE001
            log.exception("background job %s failed unexpectedly", job_id)
        finally:
            _mark_done(job_id)

    _EXECUTOR.submit(_run)


def submit_resume(cfg: AppConfig, secrets: Secrets, job_id: str, from_stage: str | None) -> None:
    """Resume `job_id` (optionally clearing outputs from `from_stage` onward) in the background."""
    _mark_running(job_id)

    def _run() -> None:
        try:
            repo = Repository(cfg.resolve(cfg.paths.db))
            try:
                orchestrator.resume(job_id, cfg, secrets, repo, from_stage=from_stage)
            finally:
                repo.close()
        except EdutubeError as e:
            log.warning("background resume %s failed: %s", job_id, e)
        except Exception:  # noqa: BLE001
            log.exception("background resume %s failed unexpectedly", job_id)
        finally:
            _mark_done(job_id)

    _EXECUTOR.submit(_run)


def submit_upload(cfg: AppConfig, secrets: Secrets, job_id: str) -> None:
    """Upload `job_id` to YouTube in the background."""
    _mark_running(job_id)

    def _run() -> None:
        try:
            repo = Repository(cfg.resolve(cfg.paths.db))
            try:
                ctx = orchestrator.build_context(job_id, cfg, secrets, repo)
                UploadStage().run(ctx)
            finally:
                repo.close()
        except EdutubeError as e:
            log.warning("background upload %s failed: %s", job_id, e)
        except Exception:  # noqa: BLE001
            log.exception("background upload %s failed unexpectedly", job_id)
        finally:
            _mark_done(job_id)

    _EXECUTOR.submit(_run)
