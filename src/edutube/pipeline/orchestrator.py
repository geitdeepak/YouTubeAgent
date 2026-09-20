"""Job orchestration: run/resume/daily (LLD §7.3, LLR-ORC-01..06)."""

from __future__ import annotations

import secrets as token_secrets
import shutil
from datetime import UTC, datetime

from edutube.config import AppConfig, Secrets
from edutube.db import Repository
from edutube.errors import StageFailedError
from edutube.llm.base import LLMProvider
from edutube.logging_setup import get_logger, job_log_handler
from edutube.media.stock import StockProvider
from edutube.media.tts import TTSProvider
from edutube.models import Job, JobStatus, Topic, VideoFormat
from edutube.pipeline.context import JobContext, JobPaths
from edutube.pipeline.stages import PIPELINE, STAGE_BY_NAME, UploadStage
from edutube.publish.quota import QuotaTracker, upload_cost
from edutube.utils.fs import job_lock
from edutube.utils.text import slugify

log = get_logger("pipeline.orchestrator")


def _make_llm(cfg: AppConfig) -> LLMProvider:
    from edutube.llm.ollama_provider import OllamaProvider

    return OllamaProvider(cfg.llm)


def _make_tts(cfg: AppConfig) -> TTSProvider:
    from edutube.media.tts import EdgeTTSProvider

    return EdgeTTSProvider(cfg.tts.pronunciations, cfg.tts.aligner_fallback)


def _make_stock(cfg: AppConfig, repo: Repository, secrets: Secrets) -> StockProvider | None:
    if not cfg.stock.enabled or secrets.pexels_api_key is None:
        return None
    from edutube.media.stock import PexelsProvider

    cache_dir = cfg.resolve(cfg.paths.workspace) / "cache" / "pexels"
    return PexelsProvider(secrets.pexels_api_key.get_secret_value(), repo, cache_dir)


def new_job_id(topic: Topic, fmt: VideoFormat) -> str:
    date_str = datetime.now(UTC).strftime("%Y%m%d")
    slug = slugify(topic.title, 30)
    suffix = token_secrets.token_hex(2)
    return f"{date_str}-{fmt.value}-{slug}-{suffix}"


def create_job(repo: Repository, topic: Topic, fmt: VideoFormat, language: str) -> Job:
    now = datetime.now(UTC)
    job = Job(
        id=new_job_id(topic, fmt),
        topic_id=topic.id,  # type: ignore[arg-type]
        format=fmt,
        language=language,
        status=JobStatus.NEW,
        created_at=now,
        updated_at=now,
    )
    repo.create_job(job)
    return job


def build_context(
    job_id: str, cfg: AppConfig, secrets: Secrets, repo: Repository, *, dry_run: bool = False
) -> JobContext:
    job = repo.get_job(job_id)
    topic = repo.get_topic(job.topic_id)
    paths = JobPaths(cfg.resolve(cfg.paths.workspace) / "jobs" / job_id)
    paths.ensure()
    return JobContext(
        job=job,
        topic=topic,
        cfg=cfg,
        secrets=secrets,
        repo=repo,
        paths=paths,
        llm=_make_llm(cfg),
        tts=_make_tts(cfg),
        stock=_make_stock(cfg, repo, secrets),
        dry_run=dry_run,
    )


def run_job(job_id: str, cfg: AppConfig, secrets: Secrets, repo: Repository, *, dry_run: bool = False) -> Job:
    """LLR-ORC-01, LLR-ORC-02: run pending stages, skip completed ones, gate at the end."""
    ctx = build_context(job_id, cfg, secrets, repo, dry_run=dry_run)
    with job_lock(ctx.paths.root), job_log_handler(ctx.paths.job_log):
        for stage in PIPELINE:
            if stage.is_done(ctx):
                log.info("skip %s (already done) job=%s", stage.name, job_id)
                continue
            log.info("running stage %s for job=%s", stage.name, job_id)
            run_id = repo.start_stage(job_id, stage.name)
            try:
                stage.run(ctx)
            except Exception as e:  # noqa: BLE001
                repo.finish_stage(run_id, "failed", error=str(e))
                repo.update_job(job_id, status=JobStatus.FAILED, failed_stage=stage.name, last_error=str(e))
                raise StageFailedError(stage.name, e) from e
            repo.finish_stage(run_id, "done")
            repo.update_job(job_id, status=stage.success_status.value, failed_stage=None, last_error=None)
            ctx.job = repo.get_job(job_id)

        gate = cfg.publish.require_approval or ctx.job.needs_human_review
        final_status = JobStatus.AWAITING_APPROVAL if gate else JobStatus.APPROVED
        repo.update_job(job_id, status=final_status.value)
    return repo.get_job(job_id)


def resume(
    job_id: str, cfg: AppConfig, secrets: Secrets, repo: Repository, *, from_stage: str | None = None
) -> Job:
    """LLR-ORC-03: resume FAILED job, optionally clearing a stage and everything after it."""
    if from_stage is not None:
        stage = STAGE_BY_NAME.get(from_stage)
        if stage is None:
            raise ValueError(f"Unknown stage '{from_stage}'. Valid: {', '.join(STAGE_BY_NAME)}")
        ctx = build_context(job_id, cfg, secrets, repo)
        idx = PIPELINE.index(stage)
        for s in PIPELINE[idx:]:
            for p in s.outputs(ctx):
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                elif p.exists():
                    p.unlink()
    return run_job(job_id, cfg, secrets, repo)


def run_daily(cfg: AppConfig, secrets: Secrets, repo: Repository, *, upload: bool = True) -> dict:
    """LLR-ORC-06: produce N shorts + M longs, then upload APPROVED jobs within quota."""
    created: list[str] = []
    failed: list[str] = []

    for fmt, count in (
        (VideoFormat.SHORT, cfg.schedule.shorts_per_day),
        (VideoFormat.LONG, cfg.schedule.longs_per_day),
    ):
        for _ in range(count):
            topic = repo.next_topic(fmt)
            if topic is None:
                log.warning("no topics available for format=%s", fmt.value)
                break
            job = create_job(repo, topic, fmt, cfg.project.language)
            try:
                run_job(job.id, cfg, secrets, repo)
                created.append(job.id)
            except StageFailedError as e:
                log.error("job %s failed: %s", job.id, e)
                failed.append(job.id)

    uploaded: list[str] = []
    if upload:
        quota = QuotaTracker(repo, cfg.quota)
        pending = sorted(repo.list_jobs(JobStatus.APPROVED), key=lambda j: j.created_at)
        for job in pending:
            cost = upload_cost(job, cfg.quota, upload_captions=cfg.publish.upload_captions)
            if not quota.can_spend(cost):
                log.warning("quota budget reached; stopping uploads for today")
                break
            ctx = build_context(job.id, cfg, secrets, repo)
            UploadStage().run(ctx)
            uploaded.append(job.id)

    return {"created": created, "failed": failed, "uploaded": uploaded}
