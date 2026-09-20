from __future__ import annotations

from datetime import UTC, datetime

from edutube.db import Repository
from edutube.models import Job, JobStatus, Topic, TopicFormat, TopicStatus, VideoFormat


def _topic(title: str = "What is a Transformer?", **kw) -> Topic:
    return Topic(title=title, created_at=datetime.now(UTC), **kw)


def test_add_and_get_topic(repo: Repository):
    tid = repo.add_topic(_topic())
    t = repo.get_topic(tid)
    assert t.title == "What is a Transformer?"
    assert t.status == TopicStatus.ACTIVE


def test_next_topic_orders_by_priority_then_age(repo: Repository):
    repo.add_topic(_topic("Low priority topic", priority=2))
    repo.add_topic(_topic("High priority topic", priority=5))
    picked = repo.next_topic(VideoFormat.SHORT)
    assert picked.title == "High priority topic"


def test_next_topic_respects_format(repo: Repository):
    repo.add_topic(_topic("Long only topic", format=TopicFormat.LONG))
    assert repo.next_topic(VideoFormat.SHORT) is None
    assert repo.next_topic(VideoFormat.LONG) is not None


def test_next_topic_skips_topics_with_active_job(repo: Repository):
    tid = repo.add_topic(_topic("Both formats", format=TopicFormat.BOTH))
    now = datetime.now(UTC)
    repo.create_job(
        Job(
            id="job1",
            topic_id=tid,
            format=VideoFormat.SHORT,
            language="en",
            status=JobStatus.NEW,
            created_at=now,
            updated_at=now,
        )
    )
    assert repo.next_topic(VideoFormat.SHORT) is None
    assert repo.next_topic(VideoFormat.LONG) is not None


def test_next_topic_retries_after_failed_job(repo: Repository):
    tid = repo.add_topic(_topic("Retry me"))
    now = datetime.now(UTC)
    repo.create_job(
        Job(
            id="job1",
            topic_id=tid,
            format=VideoFormat.SHORT,
            language="en",
            status=JobStatus.FAILED,
            created_at=now,
            updated_at=now,
        )
    )
    assert repo.next_topic(VideoFormat.SHORT) is not None


def test_find_similar_titles(repo: Repository):
    repo.add_topic(_topic("What is a Neural Network?"))
    similar = repo.find_similar_titles("what is a neural network")
    assert similar


def test_quota_usage_tracking(repo: Repository):
    assert repo.quota_used("2026-01-01") == 0
    repo.add_quota("2026-01-01", "videos.insert", 1600, "job1")
    assert repo.quota_used("2026-01-01") == 1600


def test_job_update_and_stage_runs(repo: Repository):
    tid = repo.add_topic(_topic())
    now = datetime.now(UTC)
    job = Job(
        id="job1", topic_id=tid, format=VideoFormat.SHORT, language="en",
        status=JobStatus.NEW, created_at=now, updated_at=now,
    )
    repo.create_job(job)
    run_id = repo.start_stage("job1", "script")
    repo.finish_stage(run_id, "done")
    repo.update_job("job1", status=JobStatus.SCRIPTED.value)
    updated = repo.get_job("job1")
    assert updated.status == JobStatus.SCRIPTED
    runs = repo.list_stage_runs("job1")
    assert len(runs) == 1
    assert runs[0]["status"] == "done"


def test_cache_get_put(repo: Repository):
    assert repo.cache_get("missing") is None
    repo.cache_put("pexels:1:720", "/tmp/x.mp4", {"a": 1})
    cached = repo.cache_get("pexels:1:720")
    assert cached["path"] == "/tmp/x.mp4"
    assert cached["meta"] == {"a": 1}
