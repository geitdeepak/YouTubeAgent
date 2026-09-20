from __future__ import annotations

from datetime import UTC, datetime

from edutube.config import Secrets
from edutube.db import Repository
from edutube.llm.fake_provider import FakeLLMProvider
from edutube.media.tts import FakeTTSProvider
from edutube.models import JobStatus, Topic, VideoFormat
from edutube.pipeline import orchestrator


def test_new_job_id_format():
    topic = Topic(title="What is RAG?", created_at=datetime.now(UTC))
    topic.id = 1
    job_id = orchestrator.new_job_id(topic, VideoFormat.SHORT)
    parts = job_id.split("-")
    assert parts[1] == "short"
    assert len(parts[0]) == 8  # yyyymmdd


def test_run_job_marks_failed_stage_on_exception(cfg, repo: Repository, monkeypatch):
    # An LLM with no registered responses raises KeyError on the very first stage.
    monkeypatch.setattr(orchestrator, "_make_llm", lambda cfg: FakeLLMProvider())
    monkeypatch.setattr(orchestrator, "_make_tts", lambda cfg: FakeTTSProvider())
    monkeypatch.setattr(orchestrator, "_make_stock", lambda cfg, repo, secrets: None)

    topic = Topic(title="What is a Transformer?", created_at=datetime.now(UTC))
    topic.id = repo.add_topic(topic)
    job = orchestrator.create_job(repo, topic, VideoFormat.SHORT, "en")

    from edutube.errors import StageFailedError

    try:
        orchestrator.run_job(job.id, cfg, Secrets(), repo)
        raise AssertionError("expected StageFailedError")
    except StageFailedError as e:
        assert e.stage == "script"

    failed_job = repo.get_job(job.id)
    assert failed_job.status == JobStatus.FAILED
    assert failed_job.failed_stage == "script"
    assert failed_job.last_error
