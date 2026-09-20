"""YouTube API quota tracking (LLD §8.10, LLR-QTA-01..03)."""

from __future__ import annotations

from edutube.config import QuotaCfg
from edutube.db import Repository
from edutube.models import Job, VideoFormat
from edutube.utils.timeutil import pacific_day_key


class QuotaTracker:
    def __init__(self, repo: Repository, cfg: QuotaCfg) -> None:
        self.repo = repo
        self.cfg = cfg

    def day_key(self) -> str:
        return pacific_day_key()

    def used(self) -> int:
        return self.repo.quota_used(self.day_key())

    def can_spend(self, units: int) -> bool:
        return self.used() + units <= self.cfg.daily_budget - self.cfg.safety_margin

    def record(self, units: int, op: str, job_id: str | None = None) -> None:
        self.repo.add_quota(self.day_key(), op, units, job_id)

    def mark_exhausted(self) -> None:
        remaining = max(self.cfg.daily_budget - self.used(), 0)
        if remaining:
            self.record(remaining, "exhausted", None)

    def remaining(self) -> int:
        return max(self.cfg.daily_budget - self.cfg.safety_margin - self.used(), 0)


def upload_cost(job: Job, cfg: QuotaCfg, *, upload_captions: bool) -> int:
    """Total quota cost for uploading a job: insert + thumbnail(long) + captions(long & enabled)."""
    cost = cfg.costs.videos_insert
    if job.format == VideoFormat.LONG:
        cost += cfg.costs.thumbnails_set
        if upload_captions:
            cost += cfg.costs.captions_insert
    return cost
