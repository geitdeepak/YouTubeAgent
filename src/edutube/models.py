"""Domain models (LLD §5)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from edutube.utils.text import count_words


class VideoFormat(StrEnum):
    SHORT = "short"
    LONG = "long"


class TopicFormat(StrEnum):
    SHORT = "short"
    LONG = "long"
    BOTH = "both"


class Level(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"


class TopicStatus(StrEnum):
    ACTIVE = "active"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class SceneRole(StrEnum):
    HOOK = "hook"
    INTRO = "intro"
    CONTENT = "content"
    RECAP = "recap"
    CTA = "cta"


class VisualType(StrEnum):
    TITLE = "title"
    BULLETS = "bullets"
    DEFINITION = "definition"
    COMPARISON = "comparison"
    FLOW = "flow"
    CODE = "code"
    BROLL = "broll"


class JobStatus(StrEnum):
    NEW = "NEW"
    SCRIPTED = "SCRIPTED"
    REVIEWED = "REVIEWED"
    VOICED = "VOICED"
    VISUALS_READY = "VISUALS_READY"
    RENDERED = "RENDERED"
    METADATA_READY = "METADATA_READY"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    UPLOADED = "UPLOADED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


class Topic(BaseModel):
    id: int | None = None
    title: str = Field(min_length=5, max_length=120)
    format: TopicFormat = TopicFormat.BOTH
    level: Level = Level.BEGINNER
    priority: int = Field(3, ge=1, le=5)
    keywords: list[str] = Field(default_factory=list)
    source_notes: str | None = None
    status: TopicStatus = TopicStatus.ACTIVE
    reject_reason: str | None = None
    created_at: datetime


class Job(BaseModel):
    id: str
    topic_id: int
    format: VideoFormat
    language: str
    status: JobStatus
    failed_stage: str | None = None
    last_error: str | None = None
    needs_human_review: bool = False
    reject_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class Comparison(BaseModel):
    headers: tuple[str, str]
    rows: list[tuple[str, str]] = Field(min_length=2, max_length=4)


class Scene(BaseModel):
    index: int
    role: SceneRole
    visual: VisualType
    narration: str
    on_screen_title: str = Field(max_length=60)
    chapter_title: str | None = None
    bullets: list[str] | None = None
    term: str | None = None
    definition: str | None = None
    comparison: Comparison | None = None
    flow_steps: list[str] | None = None
    code: str | None = None
    code_language: str | None = None
    broll_query: str | None = None

    @model_validator(mode="after")
    def check_visual_fields(self) -> Scene:
        """Per-type field validation (LLR-SCR-04).

        Error messages distinguish "field is missing" from "field violates a limit" and
        name the required field explicitly -- this text is fed straight back to the LLM
        as retry feedback (LLR-LLM-03), so vague messages produce vague corrections.
        """
        v = self.visual
        if v == VisualType.BULLETS:
            if self.bullets is None or len(self.bullets) == 0:
                raise ValueError(
                    f"scene {self.index} has visual='bullets' but the 'bullets' field is missing/empty; "
                    "it must be a list of 2-4 short strings"
                )
            if not (2 <= len(self.bullets) <= 4):
                raise ValueError(f"scene {self.index}: 'bullets' must have 2-4 items, got {len(self.bullets)}")
            for b in self.bullets:
                if count_words(b) > 8:
                    raise ValueError(f"scene {self.index}: bullet too long (>8 words): {b!r}")
        elif v == VisualType.DEFINITION:
            if not self.term:
                raise ValueError(
                    f"scene {self.index} has visual='definition' but the 'term' field is missing/empty; "
                    "it must be a short word or phrase of at most 4 words, e.g. 'Token'"
                )
            if count_words(self.term) > 4:
                raise ValueError(f"scene {self.index}: 'term' must be <=4 words, got {self.term!r}")
            if not self.definition:
                raise ValueError(
                    f"scene {self.index} has visual='definition' but the 'definition' field is missing/empty; "
                    "it must be a one-line explanation of at most 20 words"
                )
            if count_words(self.definition) > 20:
                raise ValueError(f"scene {self.index}: 'definition' must be <=20 words, got {self.definition!r}")
        elif v == VisualType.COMPARISON:
            if self.comparison is None:
                raise ValueError(
                    f"scene {self.index} has visual='comparison' but the 'comparison' field is missing; "
                    "it must be an object with 'headers' (2 strings) and 'rows' (2-4 pairs of strings)"
                )
        elif v == VisualType.FLOW:
            if self.flow_steps is None or len(self.flow_steps) == 0:
                raise ValueError(
                    f"scene {self.index} has visual='flow' but the 'flow_steps' field is missing/empty; "
                    "it must be a list of 2-5 short steps, each at most 3 words"
                )
            if not (2 <= len(self.flow_steps) <= 5):
                raise ValueError(f"scene {self.index}: 'flow_steps' must have 2-5 items, got {len(self.flow_steps)}")
            for s in self.flow_steps:
                if count_words(s) > 3:
                    raise ValueError(f"scene {self.index}: flow step too long (>3 words): {s!r}")
        elif v == VisualType.CODE:
            if not self.code:
                raise ValueError(
                    f"scene {self.index} has visual='code' but the 'code' field is missing/empty; "
                    "it must be a short code snippet of at most 12 lines, each at most 60 characters"
                )
            lines = self.code.splitlines()
            if len(lines) > 12:
                raise ValueError(f"scene {self.index}: 'code' must have <=12 lines, got {len(lines)}")
            for ln in lines:
                if len(ln) > 60:
                    raise ValueError(f"scene {self.index}: 'code' line too long (>60 chars): {ln!r}")
        elif v == VisualType.BROLL:
            if not self.broll_query:
                raise ValueError(
                    f"scene {self.index} has visual='broll' but the 'broll_query' field is missing/empty; "
                    "it must be 1-3 words describing stock footage to search for, e.g. 'server room'"
                )
            if not (1 <= len(self.broll_query.split()) <= 3):
                raise ValueError(f"scene {self.index}: 'broll_query' must be 1-3 words, got {self.broll_query!r}")
        return self


_SHORT_VISUAL_TYPES = {VisualType.TITLE, VisualType.BULLETS, VisualType.DEFINITION, VisualType.BROLL}


class Script(BaseModel):
    topic_title: str
    format: VideoFormat
    language: str
    title: str
    hook: str
    scenes: list[Scene] = Field(min_length=3, max_length=11)
    key_terms: list[str] = Field(default_factory=list)

    @property
    def word_count(self) -> int:
        return sum(count_words(s.narration) for s in self.scenes)

    @model_validator(mode="after")
    def check_structure(self) -> Script:
        """LLR-SCR-02: per-format scene count and role/visual-type composition."""
        n = len(self.scenes)
        roles = {s.role for s in self.scenes}
        if self.format == VideoFormat.SHORT:
            if not (3 <= n <= 5):
                raise ValueError(f"short scripts need 3-5 scenes, got {n}")
            bad = [s.visual for s in self.scenes if s.visual not in _SHORT_VISUAL_TYPES]
            if bad:
                raise ValueError(f"short scripts only allow title/bullets/definition/broll, got {bad}")
        else:
            if not (7 <= n <= 11):
                raise ValueError(f"long scripts need 7-11 scenes, got {n}")
            required = {SceneRole.HOOK, SceneRole.INTRO, SceneRole.RECAP, SceneRole.CTA}
            missing = required - roles
            if missing:
                raise ValueError(f"long scripts must include roles {required}, missing {missing}")
        return self


class Scores(BaseModel):
    accuracy: int = Field(ge=1, le=10)
    clarity: int = Field(ge=1, le=10)
    hook: int = Field(ge=1, le=10)
    beginner_friendly: int = Field(ge=1, le=10)
    structure: int = Field(ge=1, le=10)

    def min_score(self) -> int:
        return min(self.accuracy, self.clarity, self.hook, self.beginner_friendly, self.structure)


class Review(BaseModel):
    scores: Scores
    issues: list[str] = Field(default_factory=list)
    human_check_claims: list[str] = Field(default_factory=list)
    rewrite_instructions: str = ""

    def passed(self, min_score: int) -> bool:
        return self.scores.min_score() >= min_score


class Word(BaseModel):
    word: str
    start: float
    end: float


class SceneAudio(BaseModel):
    index: int
    path: Path
    duration: float
    words: list[Word]


class VoiceResult(BaseModel):
    scenes: list[SceneAudio]
    rate: str
    total_duration: float


class SceneVisual(BaseModel):
    index: int
    kind: str  # "slide" | "broll"
    path: Path
    fallback_used: bool = False


class StockAttribution(BaseModel):
    pexels_id: int
    user_name: str
    user_url: str
    video_url: str


class VideoMetadata(BaseModel):
    title: str
    description_intro: str
    key_points: list[str]
    tags: list[str]
    hashtags: list[str]
    thumbnail_text: str
    description: str = ""
    chapters: list[tuple[str, str]] = Field(default_factory=list)


class RenderInfo(BaseModel):
    path: Path
    duration: float
    width: int
    height: int
    lufs: float
    scene_starts: list[float]
