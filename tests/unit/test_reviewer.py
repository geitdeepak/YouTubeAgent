from __future__ import annotations

from pathlib import Path

from edutube.config import AppConfig
from edutube.content.reviewer import review_and_rewrite
from edutube.llm.fake_provider import FakeLLMProvider
from edutube.models import Review, Scores, Script


def _high_scores() -> Review:
    return Review(
        scores=Scores(accuracy=9, clarity=9, hook=8, beginner_friendly=9, structure=9),
        issues=[],
        human_check_claims=[],
        rewrite_instructions="",
    )


def _low_scores() -> Review:
    return Review(
        scores=Scores(accuracy=3, clarity=4, hook=3, beginner_friendly=4, structure=3),
        issues=["too technical"],
        human_check_claims=[],
        rewrite_instructions="simplify the language",
    )


def test_review_passes_on_first_try(tmp_path: Path, cfg: AppConfig, script_short: Script):
    fake = FakeLLMProvider()
    fake.register("review.md", _high_scores)
    script, review, needs_human = review_and_rewrite(fake, cfg, script_short, tmp_path)
    assert review.passed(cfg.review.min_score)
    assert needs_human is False
    assert (tmp_path / "review_1.json").exists()
    assert (tmp_path / "script.json").exists()


def test_review_rewrites_on_low_score_then_passes(tmp_path: Path, cfg: AppConfig, script_short: Script):
    fake = FakeLLMProvider()
    calls = {"n": 0}

    def review_side_effect():
        calls["n"] += 1
        return _low_scores() if calls["n"] == 1 else _high_scores()

    fake.register("review.md", review_side_effect)
    fake.register("rewrite.md", lambda: script_short)
    script, review, needs_human = review_and_rewrite(fake, cfg, script_short, tmp_path)
    assert review.passed(cfg.review.min_score)
    assert needs_human is False
    assert (tmp_path / "script_v1.json").exists()


def test_review_needs_human_after_max_iterations(tmp_path: Path, cfg: AppConfig, script_short: Script):
    fake = FakeLLMProvider()
    fake.register("review.md", _low_scores)
    fake.register("rewrite.md", lambda: script_short)
    script, review, needs_human = review_and_rewrite(fake, cfg, script_short, tmp_path)
    assert needs_human is True
    assert not review.passed(cfg.review.min_score)


def test_review_needs_human_on_human_check_claims(tmp_path: Path, cfg: AppConfig, script_short: Script):
    fake = FakeLLMProvider()
    high_with_claim = _high_scores().model_copy(update={"human_check_claims": ["GPT-5 was released in 2026"]})
    fake.register("review.md", lambda: high_with_claim)
    script, review, needs_human = review_and_rewrite(fake, cfg, script_short, tmp_path)
    assert needs_human is True
