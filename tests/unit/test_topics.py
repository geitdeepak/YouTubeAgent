from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from edutube.content.topics import add_topic, check_relevance, import_csv
from edutube.db import Repository
from edutube.llm.fake_provider import FakeLLMProvider
from edutube.models import TopicFormat, TopicStatus


def test_add_topic_valid(repo: Repository):
    topic = add_topic(repo, title="What is a Transformer?", skip_check=True)
    assert topic.id is not None
    assert topic.status == TopicStatus.ACTIVE


def test_add_topic_title_too_short(repo: Repository):
    with pytest.raises(ValidationError):
        add_topic(repo, title="Hi", skip_check=True)


def test_add_topic_relevance_rejects_low_score(repo: Repository):
    from edutube.content.topics import RelevanceResult

    fake = FakeLLMProvider()
    fake.register("relevance.md", lambda: RelevanceResult(is_ai_education=False, score=1, reason="not AI related"))
    topic = add_topic(repo, title="Best Pizza Recipes Ever", llm=fake, min_relevance=7)
    assert topic.status == TopicStatus.REJECTED
    assert topic.reject_reason == "not AI related"


def test_check_relevance_calls_llm(repo: Repository):
    from datetime import UTC, datetime

    from edutube.content.topics import RelevanceResult
    from edutube.models import Topic

    fake = FakeLLMProvider()
    fake.register("relevance.md", lambda: RelevanceResult(is_ai_education=True, score=9, reason="core AI concept"))
    topic = Topic(title="What is a Neural Network?", created_at=datetime.now(UTC))
    result = check_relevance(fake, topic)
    assert result.score == 9
    assert fake.calls[0]["prompt_name"] == "relevance.md"


def test_import_csv(tmp_path: Path, repo: Repository):
    csv_path = tmp_path / "topics.csv"
    csv_path.write_text(
        "title,format,level,priority,keywords,source_notes\n"
        "What is Artificial Intelligence?,both,beginner,5,\"ai,basics\",\n"
        "Bad,short,beginner,3,,\n"  # title too short -> should be skipped
        "Overfitting vs Underfitting,short,beginner,3,overfitting,\n",
        encoding="utf-8",
    )
    report = import_csv(repo, csv_path)
    assert report.inserted == 2
    assert len(report.skipped) == 1
    assert report.skipped[0][0] == 3  # row 2 in the file is CSV row 3 (1-indexed incl header)


def test_import_csv_missing_columns(tmp_path: Path, repo: Repository):
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("title,format\nSomething,short\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required columns"):
        import_csv(repo, csv_path)


def test_add_topic_warns_on_duplicate(repo: Repository, caplog):
    add_topic(repo, title="What is a Neural Network?", skip_check=True)
    add_topic(repo, title="what is a neural network", skip_check=True, fmt=TopicFormat.SHORT)
    # second insert succeeds regardless; duplicate detection only warns (FR-05)
    assert len(repo.list_topics()) == 2
