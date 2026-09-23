"""Topic management (LLD §8.1 relevance prompt, LLR-TOP-01..05)."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from edutube.db import Repository
from edutube.llm.base import LLMProvider
from edutube.logging_setup import get_logger
from edutube.models import Level, Topic, TopicFormat, TopicStatus

log = get_logger("content.topics")


class RelevanceResult(BaseModel):
    fits_niche: bool
    score: int = Field(ge=0, le=10)
    reason: str


@dataclass
class ImportReport:
    inserted: int = 0
    skipped: list[tuple[int, str]] = field(default_factory=list)  # (row number, reason)


CSV_HEADER = ["title", "format", "level", "priority", "keywords", "source_notes"]


def add_topic(
    repo: Repository,
    *,
    title: str,
    fmt: TopicFormat = TopicFormat.BOTH,
    level: Level = Level.BEGINNER,
    priority: int = 3,
    keywords: list[str] | None = None,
    source_notes: str | None = None,
    llm: LLMProvider | None = None,
    niche: str = "AI education",
    min_relevance: int = 7,
    skip_check: bool = False,
) -> Topic:
    """Validate, optionally relevance-check, warn on near-duplicates, then insert (LLR-TOP-01)."""
    topic = Topic(
        title=title,
        format=fmt,
        level=level,
        priority=priority,
        keywords=keywords or [],
        source_notes=source_notes,
        created_at=datetime.now(UTC),
    )

    dupes = repo.find_similar_titles(title)
    if dupes:
        log.warning("Possible duplicate topic(s): %s", ", ".join(dupes))

    if llm is not None and not skip_check:
        result = check_relevance(llm, topic, niche=niche, min_relevance=min_relevance)
        if not result.fits_niche or result.score < min_relevance:
            topic.status = TopicStatus.REJECTED
            topic.reject_reason = result.reason

    topic_id = repo.add_topic(topic)
    topic.id = topic_id
    return topic


def check_relevance(
    llm: LLMProvider, topic: Topic, *, niche: str = "AI education", min_relevance: int = 7
) -> RelevanceResult:
    """LLR-TOP-05: LLM relevance check against the configured niche (content.niche)."""
    return llm.generate_json(
        prompt_name="relevance.md",
        variables={
            "niche": niche,
            "topic": topic.title,
            "keywords": ", ".join(topic.keywords) or "none",
            "source_notes": topic.source_notes or "none",
        },
        schema=RelevanceResult,
        temperature=0.1,
    )


def import_csv(repo: Repository, path: Path) -> ImportReport:
    """Bulk import topics from a CSV file (LLR-TOP-02)."""
    report = ImportReport()
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = [h for h in CSV_HEADER if h not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"CSV is missing required columns: {missing}")
        for row_num, row in enumerate(reader, start=2):  # header is row 1
            try:
                title = (row.get("title") or "").strip()
                fmt_raw = (row.get("format") or "both").strip() or "both"
                level_raw = (row.get("level") or "beginner").strip() or "beginner"
                priority_raw = (row.get("priority") or "3").strip() or "3"
                keywords_raw = (row.get("keywords") or "").strip()
                source_notes = (row.get("source_notes") or "").strip() or None

                topic = Topic(
                    title=title,
                    format=TopicFormat(fmt_raw),
                    level=Level(level_raw),
                    priority=int(priority_raw),
                    keywords=[k.strip() for k in keywords_raw.split(",") if k.strip()],
                    source_notes=source_notes,
                    created_at=datetime.now(UTC),
                )
                repo.add_topic(topic)
                report.inserted += 1
            except (ValidationError, ValueError) as e:
                report.skipped.append((row_num, str(e)))
    return report
