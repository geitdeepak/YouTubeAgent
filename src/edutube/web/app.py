"""FastAPI app: topic submission, preview, approval and upload from a browser.

Runs entirely on the operator's own machine (see `edutube serve`); it is not
a hosted service. Reuses the same orchestrator/pipeline code as the CLI --
this module only adds routing, forms and background job submission on top.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from edutube.config import AppConfig, Secrets
from edutube.content.topics import add_topic
from edutube.db import Repository
from edutube.errors import EdutubeError
from edutube.models import Job, JobStatus, Level, Topic, TopicFormat, TopicStatus, VideoFormat
from edutube.pipeline import orchestrator
from edutube.web import runner

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

# Job states where nothing is happening in the background and the page
# doesn't need to auto-refresh.
_SETTLED_STATUSES = {
    JobStatus.AWAITING_APPROVAL,
    JobStatus.APPROVED,
    JobStatus.UPLOADED,
    JobStatus.FAILED,
    JobStatus.REJECTED,
}


def create_app(cfg: AppConfig, secrets: Secrets) -> FastAPI:
    app = FastAPI(title="EduTube Agent")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    def get_repo() -> Iterator[Repository]:
        repo = Repository(cfg.resolve(cfg.paths.db))
        try:
            yield repo
        finally:
            repo.close()

    def _job_or_404(repo: Repository, job_id: str) -> Job:
        try:
            return repo.get_job(job_id)
        except EdutubeError:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found") from None

    def _job_dir(job_id: str) -> Path:
        return cfg.resolve(cfg.paths.workspace) / "jobs" / job_id

    def _is_settled(job: Job) -> bool:
        return job.status in _SETTLED_STATUSES and not runner.is_running(job.id)

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request, repo: Repository = Depends(get_repo)) -> HTMLResponse:
        jobs = repo.list_jobs(limit=30)
        topics_by_id: dict[int, Topic | None] = {}
        for j in jobs:
            if j.topic_id not in topics_by_id:
                try:
                    topics_by_id[j.topic_id] = repo.get_topic(j.topic_id)
                except EdutubeError:
                    topics_by_id[j.topic_id] = None
        rows = [
            {"job": j, "topic": topics_by_id.get(j.topic_id), "running": runner.is_running(j.id)}
            for j in jobs
        ]
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {"rows": rows, "channel_name": cfg.project.channel_name, "niche": cfg.content.niche},
        )

    @app.post("/topics")
    def create_topic_and_job(
        title: str = Form(...),
        format: str = Form(...),  # noqa: A002 -- matches the form field name
        level: str = Form("beginner"),
        priority: int = Form(3),
        repo: Repository = Depends(get_repo),
    ) -> RedirectResponse:
        title = title.strip()
        if not title:
            raise HTTPException(status_code=422, detail="Topic title is required")
        try:
            job_format = VideoFormat(format)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=f"Invalid format: {format}") from e

        topic: Topic = add_topic(
            repo,
            title=title,
            fmt=TopicFormat.BOTH,
            level=Level(level) if level in (lv.value for lv in Level) else Level.BEGINNER,
            priority=priority,
            skip_check=True,  # keep submission instant; the safety/niche check still runs at review time
        )
        if topic.status != TopicStatus.ACTIVE:
            # Extremely unlikely with skip_check=True, but stay safe if that ever changes.
            raise HTTPException(status_code=422, detail=topic.reject_reason or "Topic was rejected")

        job = orchestrator.create_job(repo, topic, job_format, cfg.project.language)
        runner.submit_job(cfg, secrets, job.id)
        return RedirectResponse(url=f"/jobs/{job.id}", status_code=303)

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_detail(request: Request, job_id: str, repo: Repository = Depends(get_repo)) -> HTMLResponse:
        job = _job_or_404(repo, job_id)
        topic = repo.get_topic(job.topic_id)
        stage_runs = repo.list_stage_runs(job_id)
        upload = repo.get_upload(job_id)
        job_dir = _job_dir(job_id)
        return templates.TemplateResponse(
            request,
            "job_detail.html",
            {
                "job": job,
                "topic": topic,
                "stage_runs": stage_runs,
                "upload": upload,
                "has_video": (job_dir / "final.mp4").exists(),
                "has_thumb": (job_dir / "thumbnail.jpg").exists(),
                "running": runner.is_running(job_id),
                "auto_refresh": not _is_settled(job),
            },
        )

    @app.get("/api/jobs/{job_id}/status")
    def job_status(job_id: str, repo: Repository = Depends(get_repo)) -> dict:
        job = _job_or_404(repo, job_id)
        upload = repo.get_upload(job_id)
        return {
            "id": job.id,
            "status": job.status.value,
            "failed_stage": job.failed_stage,
            "last_error": job.last_error,
            "needs_human_review": job.needs_human_review,
            "running": runner.is_running(job_id),
            "upload_url": upload["url"] if upload else None,
        }

    @app.get("/jobs/{job_id}/video")
    def job_video(job_id: str, repo: Repository = Depends(get_repo)) -> FileResponse:
        _job_or_404(repo, job_id)
        path = _job_dir(job_id) / "final.mp4"
        if not path.exists():
            raise HTTPException(status_code=404, detail="Video not rendered yet")
        return FileResponse(path, media_type="video/mp4", filename="final.mp4")

    @app.get("/jobs/{job_id}/thumbnail")
    def job_thumbnail(job_id: str, repo: Repository = Depends(get_repo)) -> FileResponse:
        _job_or_404(repo, job_id)
        path = _job_dir(job_id) / "thumbnail.jpg"
        if not path.exists():
            raise HTTPException(status_code=404, detail="No thumbnail for this job")
        return FileResponse(path, media_type="image/jpeg")

    @app.post("/jobs/{job_id}/approve")
    def approve_job(job_id: str, repo: Repository = Depends(get_repo)) -> RedirectResponse:
        job = _job_or_404(repo, job_id)
        if job.status != JobStatus.AWAITING_APPROVAL:
            raise HTTPException(
                status_code=409, detail=f"Job is not AWAITING_APPROVAL (status={job.status.value})"
            )
        repo.update_job(job_id, status=JobStatus.APPROVED.value)
        return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)

    @app.post("/jobs/{job_id}/reject")
    def reject_job(job_id: str, reason: str = Form(""), repo: Repository = Depends(get_repo)) -> RedirectResponse:
        _job_or_404(repo, job_id)
        repo.update_job(
            job_id, status=JobStatus.REJECTED.value, reject_reason=reason.strip() or "Rejected via web UI"
        )
        return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)

    @app.post("/jobs/{job_id}/resume")
    def resume_job(
        job_id: str, from_stage: str = Form(""), repo: Repository = Depends(get_repo)
    ) -> RedirectResponse:
        _job_or_404(repo, job_id)
        runner.submit_resume(cfg, secrets, job_id, from_stage.strip() or None)
        return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)

    @app.post("/jobs/{job_id}/upload")
    def upload_job(job_id: str, repo: Repository = Depends(get_repo)) -> RedirectResponse:
        job = _job_or_404(repo, job_id)
        if job.status != JobStatus.APPROVED:
            raise HTTPException(status_code=409, detail=f"Job is not APPROVED (status={job.status.value})")
        runner.submit_upload(cfg, secrets, job_id)
        return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)

    return app
