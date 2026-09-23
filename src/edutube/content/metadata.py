"""SEO metadata generation and assembly (LLD §8.8, LLR-MET-01..06)."""

from __future__ import annotations

import json
from pathlib import Path

from edutube.config import AppConfig
from edutube.llm.base import LLMProvider
from edutube.logging_setup import get_logger
from edutube.models import RenderInfo, Script, StockAttribution, VideoFormat, VideoMetadata
from edutube.utils.timeutil import fmt_chapter_time

log = get_logger("content.metadata")

MAX_TITLE_LEN = 70
MAX_DESCRIPTION_LEN = 5000
MAX_TAG_LEN = 30
MAX_TAGS_TOTAL_LEN = 450
MIN_CHAPTER_S = 10.0
MIN_CHAPTERS = 3


def generate_metadata(
    llm: LLMProvider, cfg: AppConfig, script: Script, *, log_dir: Path | None = None
) -> VideoMetadata:
    """LLR-MET-01: ask the LLM for the raw metadata fields."""
    meta = llm.generate_json(
        prompt_name="metadata.md",
        variables={
            "channel_name": cfg.project.channel_name,
            "style_guide": cfg.content.style_guide,
            "niche": cfg.content.niche,
            "banned_title_words": ", ".join(cfg.content.banned_title_words),
            "topic": script.topic_title,
            "format": script.format.value,
            "key_terms": ", ".join(script.key_terms) or "none",
            "hook": script.hook,
        },
        schema=VideoMetadata,
        temperature=cfg.llm.temperature,
        log_dir=log_dir,
    )
    return meta


def finalize_title(meta: VideoMetadata, cfg: AppConfig, fmt: VideoFormat) -> str:
    """LLR-MET-02: truncate at word boundary, strip banned words, add #Shorts."""
    title = meta.title
    for banned in cfg.content.banned_title_words:
        if banned.lower() in title.lower():
            title = title.replace(banned, "").replace(banned.title(), "").replace(banned.upper(), "")
    title = " ".join(title.split())

    suffix = " #Shorts" if fmt == VideoFormat.SHORT and "#shorts" not in title.lower() else ""
    budget = MAX_TITLE_LEN - len(suffix)
    if len(title) > budget:
        truncated = title[:budget].rsplit(" ", 1)[0]
        title = truncated
    return (title + suffix).strip()


def build_chapters(script: Script, scene_starts: list[float]) -> list[tuple[str, str]]:
    """LLR-MET-05: chapters from scene start times of scenes with chapter_title."""
    raw: list[tuple[float, str]] = [
        (scene_starts[s.index], s.chapter_title)
        for s in script.scenes
        if s.chapter_title and s.index < len(scene_starts)
    ]
    if not raw:
        return []
    raw.sort(key=lambda x: x[0])
    if raw[0][0] != 0.0:
        raw[0] = (0.0, raw[0][1])

    merged: list[tuple[float, str]] = [raw[0]]
    for t, title in raw[1:]:
        if t - merged[-1][0] < MIN_CHAPTER_S:
            continue  # merge into previous chapter (drop this boundary)
        merged.append((t, title))

    if len(merged) < MIN_CHAPTERS:
        return []
    return [(fmt_chapter_time(t), title) for t, title in merged]


def assemble_tags(tags: list[str]) -> list[str]:
    """LLR-MET-04: dedupe, each <=30 chars, total joined length <=450 chars."""
    seen: set[str] = set()
    result: list[str] = []
    total_len = 0
    for tag in tags:
        tag = tag.strip()[:MAX_TAG_LEN]
        key = tag.lower()
        if not tag or key in seen:
            continue
        added_len = len(tag) + (1 if result else 0)
        if total_len + added_len > MAX_TAGS_TOTAL_LEN:
            break
        seen.add(key)
        result.append(tag)
        total_len += added_len
    return result


def assemble_description(
    meta: VideoMetadata,
    cfg: AppConfig,
    fmt: VideoFormat,
    chapters: list[tuple[str, str]],
    attributions: list[StockAttribution],
) -> str:
    """LLR-MET-03: intro, key points, chapters (Long), credits, AI note, hashtags."""
    parts: list[str] = [meta.description_intro.strip(), ""]

    parts.append("In this video:")
    for point in meta.key_points:
        parts.append(f"• {point}")
    parts.append("")

    if fmt == VideoFormat.LONG and chapters:
        parts.append("Chapters:")
        for ts, title in chapters:
            parts.append(f"{ts} {title}")
        parts.append("")

    if attributions:
        parts.append("Credits:")
        for a in attributions:
            parts.append(f"Stock footage from Pexels — {a.user_name} ({a.video_url})")
        parts.append("")

    parts.append(cfg.content.ai_disclosure_text)
    parts.append("")

    hashtags = list(meta.hashtags)
    if fmt == VideoFormat.SHORT and "#shorts" not in " ".join(hashtags).lower():
        hashtags.append("#Shorts")
    parts.append(" ".join(hashtags))

    description = "\n".join(parts)
    description = description.replace("<", "").replace(">", "")

    if len(description) > MAX_DESCRIPTION_LEN:
        description = description[:MAX_DESCRIPTION_LEN]
    return description.strip()


def build_video_metadata(
    llm: LLMProvider,
    cfg: AppConfig,
    script: Script,
    render: RenderInfo,
    attributions: list[StockAttribution],
    *,
    log_dir: Path | None = None,
) -> VideoMetadata:
    """Full LLR-MET-01..06 pipeline: generate, finalize, assemble, save-ready."""
    meta = generate_metadata(llm, cfg, script, log_dir=log_dir)
    meta.title = finalize_title(meta, cfg, script.format)
    meta.tags = assemble_tags(meta.tags)
    meta.chapters = build_chapters(script, render.scene_starts)
    meta.description = assemble_description(meta, cfg, script.format, meta.chapters, attributions)
    return meta


def save_metadata(meta: VideoMetadata, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(meta.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8"
    )
