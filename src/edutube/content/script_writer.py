"""Script generation and editing (LLD §8.1, LLR-SCR-01..07)."""

from __future__ import annotations

import json
from pathlib import Path

from edutube.config import AppConfig, FormatSpec
from edutube.errors import ScriptLengthError
from edutube.llm.base import LLMProvider
from edutube.logging_setup import get_logger
from edutube.models import Review, Script, Topic, VideoFormat, VisualType

log = get_logger("content.script_writer")

_SCENE_PLAN_NOTE = {
    VideoFormat.SHORT: "3-5 scenes: hook + 2-3 content + cta",
    VideoFormat.LONG: "7-11 scenes: hook, intro, 3-6 content, recap, cta",
}


def _prompt_name(fmt: VideoFormat) -> str:
    return "script_short.md" if fmt == VideoFormat.SHORT else "script_long.md"


def write_script(
    llm: LLMProvider,
    cfg: AppConfig,
    topic: Topic,
    fmt: VideoFormat,
    *,
    language: str | None = None,
    log_dir: Path | None = None,
) -> Script:
    """Generate a new script for `topic` (LLR-SCR-01, LLR-SCR-06)."""
    spec = cfg.formats[fmt.value]
    variables = _base_variables(cfg, topic, fmt, spec, language or cfg.project.language)
    script = llm.generate_json(
        prompt_name=_prompt_name(fmt),
        variables=variables,
        schema=Script,
        temperature=cfg.llm.temperature,
        log_dir=log_dir,
    )
    script = enforce_word_range(llm, cfg, script, spec, log_dir=log_dir)
    script = enforce_broll_ratio(script)
    return script


def _base_variables(cfg: AppConfig, topic: Topic, fmt: VideoFormat, spec: FormatSpec, language: str) -> dict[str, str]:
    return {
        "channel_name": cfg.project.channel_name,
        "style_guide": cfg.content.style_guide,
        "niche": cfg.content.niche,
        "topic": topic.title,
        "level": topic.level.value,
        "format": fmt.value,
        "min_s": str(spec.min_s),
        "max_s": str(spec.max_s),
        "min_words": str(spec.min_words),
        "max_words": str(spec.max_words),
        "language": language,
        "source_notes": topic.source_notes or "none",
    }


def enforce_word_range(
    llm: LLMProvider,
    cfg: AppConfig,
    script: Script,
    spec: FormatSpec,
    *,
    log_dir: Path | None = None,
) -> Script:
    """LLR-SCR-03: one adjust-length call if outside range; ±10% tolerance after that."""
    if spec.min_words <= script.word_count <= spec.max_words:
        return script

    direction = "Shorten" if script.word_count > spec.max_words else "Lengthen"
    script = adjust_length(llm, cfg, script, spec, direction, log_dir=log_dir)

    if spec.min_words <= script.word_count <= spec.max_words:
        return script

    tolerance_min = spec.min_words * 0.9
    tolerance_max = spec.max_words * 1.1
    if tolerance_min <= script.word_count <= tolerance_max:
        log.warning(
            "script word count %d outside %d-%d but within 10%% tolerance",
            script.word_count,
            spec.min_words,
            spec.max_words,
        )
        return script

    raise ScriptLengthError(
        f"script has {script.word_count} words, target is {spec.min_words}-{spec.max_words}"
    )


def adjust_length(
    llm: LLMProvider,
    cfg: AppConfig,
    script: Script,
    spec: FormatSpec,
    direction: str,
    *,
    log_dir: Path | None = None,
) -> Script:
    return llm.generate_json(
        prompt_name="adjust_length.md",
        variables={
            "channel_name": cfg.project.channel_name,
            "style_guide": cfg.content.style_guide,
            "niche": cfg.content.niche,
            "current_words": str(script.word_count),
            "min_words": str(spec.min_words),
            "max_words": str(spec.max_words),
            "direction": direction,
            "script_json": script.model_dump_json(indent=2),
        },
        schema=Script,
        temperature=0.3,
        log_dir=log_dir,
    )


def enforce_broll_ratio(script: Script) -> Script:
    """LLR-SCR-05: long scripts need >=60% non-broll scenes; convert excess broll to title."""
    if script.format != VideoFormat.LONG:
        return script
    n = len(script.scenes)
    min_non_broll = _ceil_div(n * 6, 10)  # ceil(60% of n)
    max_broll = n - min_non_broll
    broll_indices = [i for i, s in enumerate(script.scenes) if s.visual == VisualType.BROLL]
    excess = len(broll_indices) - max_broll
    if excess <= 0:
        return script
    for i in broll_indices[:excess]:
        scene = script.scenes[i]
        script.scenes[i] = scene.model_copy(update={"visual": VisualType.TITLE, "broll_query": None})
    return script


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b)


def rewrite_script(
    llm: LLMProvider,
    cfg: AppConfig,
    script: Script,
    review: Review,
    *,
    log_dir: Path | None = None,
) -> Script:
    """Rewrite the script using reviewer feedback (LLR-REV-03)."""
    spec = cfg.formats[script.format.value]
    return llm.generate_json(
        prompt_name="rewrite.md",
        variables={
            "channel_name": cfg.project.channel_name,
            "style_guide": cfg.content.style_guide,
            "niche": cfg.content.niche,
            "min_words": str(spec.min_words),
            "max_words": str(spec.max_words),
            "script_json": script.model_dump_json(indent=2),
            "issues": "; ".join(review.issues) or "none",
            "human_check_claims": "; ".join(review.human_check_claims) or "none",
            "rewrite_instructions": review.rewrite_instructions or "Improve overall quality.",
        },
        schema=Script,
        temperature=cfg.llm.temperature,
        log_dir=log_dir,
    )


def save_script(script: Script, path: Path) -> None:
    """Save script.json pretty-printed, UTF-8 (LLR-SCR-07)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(script.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_script(path: Path) -> Script:
    return Script.model_validate_json(path.read_text(encoding="utf-8"))
