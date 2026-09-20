"""Configuration loading (LLD §4, LLR-CFG-01..06).

Config values live in ``config.yaml`` (validated into :class:`AppConfig`);
secrets live in the environment / ``.env`` (validated into :class:`Secrets`).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from edutube.errors import ConfigError

DEFAULT_CONFIG_FILENAME = "config.yaml"
ENV_VAR = "EDUTUBE_CONFIG"


class ProjectCfg(BaseModel):
    channel_name: str = "AI Simplified"
    language: Literal["en", "hi"] = "en"
    timezone: str = "Asia/Kolkata"


class LLMCfg(BaseModel):
    provider: str = "ollama"
    model: str = "llama3.1:8b"
    host: str = "http://localhost:11434"
    temperature: float = 0.7
    review_temperature: float = 0.2
    timeout_s: float = 300
    num_ctx: int = 8192


class ContentCfg(BaseModel):
    niche: str = "AI education"
    min_relevance: int = 7
    style_guide: str = (
        "Friendly teacher tone. Explain like to a smart beginner. One analogy per concept. "
        "Short sentences. No hype, no clickbait. Avoid statistics and dates unless in source notes."
    )
    banned_title_words: list[str] = Field(
        default_factory=lambda: ["shocking", "insane", "you won't believe"]
    )
    ai_disclosure_text: str = (
        "This video was produced with AI assistance (script drafting and synthetic voice) "
        "and reviewed by the creator."
    )


class FormatSpec(BaseModel):
    width: int
    height: int
    min_s: float
    max_s: float
    min_words: int
    max_words: int

    @property
    def target_s(self) -> float:
        return (self.min_s + self.max_s) / 2


def _default_formats() -> dict[Literal["short", "long"], FormatSpec]:
    return {
        "short": FormatSpec(width=1080, height=1920, min_s=30, max_s=40, min_words=75, max_words=100),
        "long": FormatSpec(width=1920, height=1080, min_s=240, max_s=300, min_words=600, max_words=750),
    }


class ReviewCfg(BaseModel):
    min_score: int = 7
    max_iterations: int = 2


class TTSCfg(BaseModel):
    provider: str = "edge"
    voices: dict[str, str] = Field(
        default_factory=lambda: {"en": "en-IN-PrabhatNeural", "hi": "hi-IN-MadhurNeural"}
    )
    rate: str = "+0%"
    pitch: str = "+0Hz"
    pronunciations: dict[str, str] = Field(
        default_factory=lambda: {
            "LLM": "L L M",
            "LLMs": "L L Ms",
            "GPT": "G P T",
            "RAG": "rag",
            "API": "A P I",
            "GPU": "G P U",
            "NLP": "N L P",
        }
    )
    aligner_fallback: Literal["faster-whisper", "even"] = "faster-whisper"


class StockCfg(BaseModel):
    provider: str = "pexels"
    enabled: bool = True
    min_height: int = 720


class BrandCfg(BaseModel):
    primary: str = "#1E3A8A"
    accent: str = "#FACC15"
    background: str = "#0B1020"
    text: str = "#FFFFFF"
    font_bold: str = "assets/fonts/Poppins-Bold.ttf"
    font_regular: str = "assets/fonts/Poppins-Regular.ttf"
    font_mono: str = "assets/fonts/JetBrainsMono-Regular.ttf"
    font_hindi: str = "assets/fonts/NotoSansDevanagari-Regular.ttf"
    logo: str = "assets/brand/logo.png"
    intro_clip: str | None = None
    outro_clip: str | None = None


class RenderCfg(BaseModel):
    fps: int = 30
    crf: int = 20
    preset: str = "medium"
    scene_padding_s: float = 0.25
    fade_s: float = 0.2
    ken_burns: bool = True
    music_enabled: bool = True
    music_dir: str = "assets/music"
    music_volume_db: float = -20
    target_lufs: float = -14
    parallel_clips: int = 1


class PublishCfg(BaseModel):
    require_approval: bool = True
    privacy_status: Literal["private", "unlisted", "public"] = "private"
    contains_synthetic_media: bool = True
    upload_captions: bool = True
    category_id: str = "27"
    default_language: str = "en"
    schedule_publish_time: str | None = None


class QuotaCosts(BaseModel):
    videos_insert: int = 1600
    thumbnails_set: int = 50
    captions_insert: int = 400


class QuotaCfg(BaseModel):
    daily_budget: int = 10000
    safety_margin: int = 500
    costs: QuotaCosts = Field(default_factory=QuotaCosts)


class ScheduleCfg(BaseModel):
    shorts_per_day: int = 1
    longs_per_day: int = 0
    run_time: str = "06:00"


class PathsCfg(BaseModel):
    db: str = "data/edutube.db"
    workspace: str = "workspace"
    logs: str = "logs"
    secrets: str = "secrets"
    topics_csv: str = "data/topics.csv"


class AppConfig(BaseModel):
    project: ProjectCfg = Field(default_factory=ProjectCfg)
    llm: LLMCfg = Field(default_factory=LLMCfg)
    content: ContentCfg = Field(default_factory=ContentCfg)
    formats: dict[Literal["short", "long"], FormatSpec] = Field(default_factory=_default_formats)
    review: ReviewCfg = Field(default_factory=ReviewCfg)
    tts: TTSCfg = Field(default_factory=TTSCfg)
    stock: StockCfg = Field(default_factory=StockCfg)
    brand: BrandCfg = Field(default_factory=BrandCfg)
    render: RenderCfg = Field(default_factory=RenderCfg)
    publish: PublishCfg = Field(default_factory=PublishCfg)
    quota: QuotaCfg = Field(default_factory=QuotaCfg)
    schedule: ScheduleCfg = Field(default_factory=ScheduleCfg)
    paths: PathsCfg = Field(default_factory=PathsCfg)

    root: Path = Field(default_factory=Path.cwd, exclude=True)

    model_config = {"arbitrary_types_allowed": True}

    def resolve(self, p: str | Path) -> Path:
        """Resolve a possibly-relative path against the project root (LLR-CFG-05)."""
        path = Path(p)
        return path if path.is_absolute() else self.root / path


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    pexels_api_key: SecretStr | None = None


def _default_config_path(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    env_path = os.environ.get(ENV_VAR)
    if env_path:
        return Path(env_path)
    return Path.cwd() / DEFAULT_CONFIG_FILENAME


def load_config(path: Path | None = None) -> AppConfig:
    """Load and validate ``config.yaml`` into an :class:`AppConfig` (LLR-CFG-01, LLR-CFG-03)."""
    config_path = _default_config_path(path)
    if not config_path.exists():
        raise ConfigError(
            f"Config file not found: {config_path}",
            hint="Run `edutube init` to create a default config.yaml",
        )
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {config_path}: {e}") from e

    if not isinstance(raw, dict):
        raise ConfigError(f"{config_path} must contain a YAML mapping at the top level")

    try:
        cfg = AppConfig(**raw, root=config_path.resolve().parent)
    except ValidationError as e:
        lines = [f"Invalid configuration in {config_path}:"]
        for err in e.errors():
            loc = ".".join(str(p) for p in err["loc"])
            lines.append(f"  - {loc}: {err['msg']}")
        raise ConfigError("\n".join(lines)) from e
    return cfg


def load_secrets(env_file: Path | None = None) -> Secrets:
    if env_file is not None and env_file.exists():
        return Secrets(_env_file=str(env_file))  # type: ignore[call-arg]
    return Secrets()
