from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from edutube.config import AppConfig
from edutube.db import Repository
from edutube.models import Job, JobStatus, Topic, VideoFormat, VideoMetadata
from edutube.publish.quota import QuotaTracker
from edutube.publish.uploader import Uploader, build_request_body


def _meta() -> VideoMetadata:
    return VideoMetadata(
        title="What is RAG? #Shorts",
        description_intro="x",
        key_points=[],
        tags=["ai", "rag"],
        hashtags=["#AI"],
        thumbnail_text="RAG EXPLAINED",
        description="Full description here.",
    )


def test_build_request_body_defaults(cfg: AppConfig):
    body = build_request_body(_meta(), cfg.publish, cfg.project.timezone)
    assert body["snippet"]["title"] == "What is RAG? #Shorts"
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["containsSyntheticMedia"] is True
    assert "publishAt" not in body["status"]


def test_build_request_body_with_schedule(cfg: AppConfig):
    cfg.publish.schedule_publish_time = "18:00"
    body = build_request_body(_meta(), cfg.publish, cfg.project.timezone)
    assert body["status"]["publishAt"].endswith("Z")


def test_dry_run_makes_no_network_call(cfg: AppConfig, repo: Repository, tmp_path: Path, capsys):
    now = datetime.now(UTC)
    topic_id = repo.add_topic(Topic(title="What is RAG?", created_at=now))
    job = Job(
        id="job1", topic_id=topic_id, format=VideoFormat.SHORT, language="en",
        status=JobStatus.APPROVED, created_at=now, updated_at=now,
    )
    repo.create_job(job)
    final_mp4 = tmp_path / "final.mp4"
    final_mp4.write_bytes(b"fake video bytes")

    quota = QuotaTracker(repo, cfg.quota)
    uploader = Uploader(repo, quota, cfg, tmp_path / "token.json")
    result = uploader.upload(job, _meta(), final_mp4, dry_run=True)

    assert result.dry_run is True
    captured = capsys.readouterr()
    assert '"privacyStatus": "private"' in captured.out
    assert "final.mp4" in captured.out


def test_already_uploaded_short_circuits(cfg: AppConfig, repo: Repository, tmp_path: Path):
    now = datetime.now(UTC)
    topic_id = repo.add_topic(Topic(title="What is RAG?", created_at=now))
    job = Job(
        id="job1", topic_id=topic_id, format=VideoFormat.SHORT, language="en",
        status=JobStatus.APPROVED, created_at=now, updated_at=now,
    )
    repo.create_job(job)
    repo.record_upload("job1", "abc123", "https://youtu.be/abc123", "private")

    quota = QuotaTracker(repo, cfg.quota)
    uploader = Uploader(repo, quota, cfg, tmp_path / "token.json")
    result = uploader.upload(job, _meta(), tmp_path / "final.mp4")
    assert result.already_uploaded is True
    assert result.video_id == "abc123"
