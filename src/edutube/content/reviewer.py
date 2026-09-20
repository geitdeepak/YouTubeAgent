"""Script self-review (LLD §8.1, LLR-REV-01..05)."""

from __future__ import annotations

import json
from pathlib import Path

from edutube.config import AppConfig
from edutube.content.script_writer import rewrite_script, save_script
from edutube.llm.base import LLMProvider
from edutube.logging_setup import get_logger
from edutube.models import Review, Script

log = get_logger("content.reviewer")


def review_script(
    llm: LLMProvider, cfg: AppConfig, script: Script, *, log_dir: Path | None = None
) -> Review:
    return llm.generate_json(
        prompt_name="review.md",
        variables={"script_json": script.model_dump_json(indent=2)},
        schema=Review,
        temperature=cfg.llm.review_temperature,
        log_dir=log_dir,
    )


def review_and_rewrite(
    llm: LLMProvider,
    cfg: AppConfig,
    script: Script,
    job_dir: Path,
    *,
    log_dir: Path | None = None,
) -> tuple[Script, Review, bool]:
    """Run the review/rewrite loop (LLR-REV-02..04).

    Returns (final_script, final_review, needs_human_review).
    """
    min_score = cfg.review.min_score
    max_iterations = cfg.review.max_iterations

    review = review_script(llm, cfg, script, log_dir=log_dir)
    _save_review(job_dir, 1, review)

    iteration = 1
    while not review.passed(min_score) and iteration <= max_iterations:
        _save_script_version(job_dir, iteration, script)
        script = rewrite_script(llm, cfg, script, review, log_dir=log_dir)
        review = review_script(llm, cfg, script, log_dir=log_dir)
        iteration += 1
        _save_review(job_dir, iteration, review)

    needs_human_review = not review.passed(min_score) or bool(review.human_check_claims)
    save_script(script, job_dir / "script.json")
    return script, review, needs_human_review


def _save_review(job_dir: Path, n: int, review: Review) -> None:
    path = job_dir / f"review_{n}.json"
    path.write_text(
        json.dumps(review.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _save_script_version(job_dir: Path, n: int, script: Script) -> None:
    save_script(script, job_dir / f"script_v{n}.json")
