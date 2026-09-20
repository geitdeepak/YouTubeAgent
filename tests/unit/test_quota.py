from __future__ import annotations

from datetime import UTC, datetime

from edutube.config import QuotaCfg
from edutube.db import Repository
from edutube.models import Job, JobStatus, VideoFormat
from edutube.publish.quota import QuotaTracker, upload_cost


def test_can_spend_within_budget(repo: Repository):
    tracker = QuotaTracker(repo, QuotaCfg(daily_budget=10000, safety_margin=500))
    assert tracker.can_spend(1600) is True


def test_can_spend_respects_margin(repo: Repository):
    cfg = QuotaCfg(daily_budget=2000, safety_margin=500)
    tracker = QuotaTracker(repo, cfg)
    tracker.record(1400, "videos.insert", "job1")
    assert tracker.can_spend(200) is False  # 1400+200=1600 > 2000-500=1500
    assert tracker.can_spend(90) is True


def test_upload_cost_short_vs_long():
    cfg = QuotaCfg()
    now = datetime.now(UTC)
    short_job = Job(
        id="j1", topic_id=1, format=VideoFormat.SHORT, language="en", status=JobStatus.APPROVED,
        created_at=now, updated_at=now,
    )
    long_job = short_job.model_copy(update={"format": VideoFormat.LONG})
    assert upload_cost(short_job, cfg, upload_captions=True) == cfg.costs.videos_insert
    assert upload_cost(long_job, cfg, upload_captions=True) == (
        cfg.costs.videos_insert + cfg.costs.thumbnails_set + cfg.costs.captions_insert
    )
    assert upload_cost(long_job, cfg, upload_captions=False) == cfg.costs.videos_insert + cfg.costs.thumbnails_set
