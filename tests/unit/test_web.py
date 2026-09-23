"""Web UI routes: FastAPI TestClient against a temp project, background jobs stubbed out."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from edutube.config import AppConfig, Secrets
from edutube.db import Repository
from edutube.models import Job, JobStatus, Topic, VideoFormat
from edutube.web import runner
from edutube.web.app import create_app


@pytest.fixture()
def client(cfg: AppConfig, monkeypatch) -> TestClient:
    monkeypatch.setattr(runner, "submit_job", lambda *a, **k: None)
    monkeypatch.setattr(runner, "submit_resume", lambda *a, **k: None)
    monkeypatch.setattr(runner, "submit_upload", lambda *a, **k: None)
    app = create_app(cfg, Secrets())
    return TestClient(app)


def _make_job(repo: Repository, *, status: JobStatus = JobStatus.AWAITING_APPROVAL, fmt=VideoFormat.SHORT) -> Job:
    now = datetime.now(UTC)
    topic = Topic(title="What is RAG?", created_at=now)
    topic.id = repo.add_topic(topic)
    job = Job(
        id="job1", topic_id=topic.id, format=fmt, language="en", status=status, created_at=now, updated_at=now
    )
    repo.create_job(job)
    return job


def test_dashboard_empty(client: TestClient):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "No jobs yet" in resp.text


def test_dashboard_lists_jobs(client: TestClient, repo: Repository):
    _make_job(repo)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "What is RAG?" in resp.text
    assert "AWAITING_APPROVAL" in resp.text


def test_create_topic_and_job_submits_background_job(client: TestClient, repo: Repository, monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "submit_job", lambda cfg, secrets, job_id: calls.append(job_id))
    resp = client.post(
        "/topics",
        data={"title": "What is a Transformer?", "format": "short", "level": "beginner", "priority": "4"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert len(calls) == 1
    jobs = repo.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].format == VideoFormat.SHORT
    assert resp.headers["location"] == f"/jobs/{jobs[0].id}"


def test_create_topic_requires_nonblank_title(client: TestClient):
    resp = client.post("/topics", data={"title": "   ", "format": "short"})
    assert resp.status_code == 422


def test_create_topic_rejects_bad_format(client: TestClient):
    resp = client.post("/topics", data={"title": "Valid Title Here", "format": "medium"})
    assert resp.status_code == 422


def test_job_detail_404_for_unknown_job(client: TestClient):
    resp = client.get("/jobs/does-not-exist")
    assert resp.status_code == 404


def test_job_detail_shows_status_and_approve_form(client: TestClient, repo: Repository):
    job = _make_job(repo)
    resp = client.get(f"/jobs/{job.id}")
    assert resp.status_code == 200
    assert "AWAITING_APPROVAL" in resp.text
    assert "Approve" in resp.text


def test_approve_transitions_status(client: TestClient, repo: Repository):
    job = _make_job(repo, status=JobStatus.AWAITING_APPROVAL)
    resp = client.post(f"/jobs/{job.id}/approve", follow_redirects=False)
    assert resp.status_code == 303
    assert repo.get_job(job.id).status == JobStatus.APPROVED


def test_approve_rejects_wrong_status(client: TestClient, repo: Repository):
    job = _make_job(repo, status=JobStatus.NEW)
    resp = client.post(f"/jobs/{job.id}/approve")
    assert resp.status_code == 409


def test_reject_sets_reason(client: TestClient, repo: Repository):
    job = _make_job(repo, status=JobStatus.AWAITING_APPROVAL)
    resp = client.post(f"/jobs/{job.id}/reject", data={"reason": "not good enough"}, follow_redirects=False)
    assert resp.status_code == 303
    updated = repo.get_job(job.id)
    assert updated.status == JobStatus.REJECTED
    assert updated.reject_reason == "not good enough"


def test_reject_defaults_reason_when_blank(client: TestClient, repo: Repository):
    job = _make_job(repo, status=JobStatus.AWAITING_APPROVAL)
    client.post(f"/jobs/{job.id}/reject", data={"reason": ""}, follow_redirects=False)
    assert repo.get_job(job.id).reject_reason == "Rejected via web UI"


def test_upload_requires_approved_status(client: TestClient, repo: Repository):
    job = _make_job(repo, status=JobStatus.AWAITING_APPROVAL)
    resp = client.post(f"/jobs/{job.id}/upload")
    assert resp.status_code == 409


def test_upload_submits_background_upload(client: TestClient, repo: Repository, monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "submit_upload", lambda cfg, secrets, job_id: calls.append(job_id))
    job = _make_job(repo, status=JobStatus.APPROVED)
    resp = client.post(f"/jobs/{job.id}/upload", follow_redirects=False)
    assert resp.status_code == 303
    assert calls == [job.id]


def test_resume_submits_background_resume(client: TestClient, repo: Repository, monkeypatch):
    calls = []
    monkeypatch.setattr(
        runner, "submit_resume", lambda cfg, secrets, job_id, from_stage: calls.append((job_id, from_stage))
    )
    job = _make_job(repo, status=JobStatus.FAILED)
    resp = client.post(f"/jobs/{job.id}/resume", data={"from_stage": "voice"}, follow_redirects=False)
    assert resp.status_code == 303
    assert calls == [(job.id, "voice")]


def test_resume_with_blank_stage_passes_none(client: TestClient, repo: Repository, monkeypatch):
    calls = []
    monkeypatch.setattr(
        runner, "submit_resume", lambda cfg, secrets, job_id, from_stage: calls.append(from_stage)
    )
    job = _make_job(repo, status=JobStatus.FAILED)
    client.post(f"/jobs/{job.id}/resume", data={"from_stage": ""}, follow_redirects=False)
    assert calls == [None]


def test_video_404_when_not_rendered(client: TestClient, repo: Repository):
    job = _make_job(repo)
    resp = client.get(f"/jobs/{job.id}/video")
    assert resp.status_code == 404


def test_video_served_when_present(client: TestClient, repo: Repository, cfg: AppConfig):
    job = _make_job(repo)
    job_dir = cfg.resolve(cfg.paths.workspace) / "jobs" / job.id
    job_dir.mkdir(parents=True)
    (job_dir / "final.mp4").write_bytes(b"fake mp4 bytes")
    resp = client.get(f"/jobs/{job.id}/video")
    assert resp.status_code == 200
    assert resp.content == b"fake mp4 bytes"


def test_thumbnail_404_when_absent(client: TestClient, repo: Repository):
    job = _make_job(repo)
    resp = client.get(f"/jobs/{job.id}/thumbnail")
    assert resp.status_code == 404


def test_status_api_reflects_db_state(client: TestClient, repo: Repository):
    job = _make_job(repo)
    resp = client.get(f"/api/jobs/{job.id}/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "AWAITING_APPROVAL"
    assert data["upload_url"] is None
    assert data["running"] is False


def test_status_api_includes_upload_url_once_uploaded(client: TestClient, repo: Repository):
    job = _make_job(repo, status=JobStatus.UPLOADED)
    repo.record_upload(job.id, "abc123", "https://youtu.be/abc123", "private")
    resp = client.get(f"/api/jobs/{job.id}/status")
    assert resp.json()["upload_url"] == "https://youtu.be/abc123"
