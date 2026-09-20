"""Job context and file-path helpers (LLD §7.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from edutube.config import AppConfig, FormatSpec, Secrets
from edutube.db import Repository
from edutube.llm.base import LLMProvider
from edutube.media.stock import StockProvider
from edutube.media.tts import TTSProvider
from edutube.models import Job, Topic


@dataclass
class JobPaths:
    root: Path

    def ensure(self) -> None:
        for sub in ("audio", "slides", "broll", "clips", "llm"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    @property
    def audio_dir(self) -> Path:
        return self.root / "audio"

    @property
    def slides_dir(self) -> Path:
        return self.root / "slides"

    @property
    def broll_dir(self) -> Path:
        return self.root / "broll"

    @property
    def clips_dir(self) -> Path:
        return self.root / "clips"

    @property
    def llm_dir(self) -> Path:
        return self.root / "llm"

    @property
    def script(self) -> Path:
        return self.root / "script.json"

    def script_version(self, n: int) -> Path:
        return self.root / f"script_v{n}.json"

    def review(self, n: int) -> Path:
        return self.root / f"review_{n}.json"

    def scene_mp3(self, i: int) -> Path:
        return self.audio_dir / f"scene_{i}.mp3"

    def scene_words(self, i: int) -> Path:
        return self.audio_dir / f"scene_{i}.words.json"

    @property
    def voice_json(self) -> Path:
        return self.root / "voice.json"

    def slide_png(self, i: int) -> Path:
        return self.slides_dir / f"scene_{i}.png"

    def broll_mp4(self, i: int) -> Path:
        return self.broll_dir / f"scene_{i}.mp4"

    @property
    def visuals_json(self) -> Path:
        return self.root / "visuals.json"

    @property
    def assets_json(self) -> Path:
        return self.root / "assets.json"

    @property
    def overlay_title(self) -> Path:
        return self.root / "overlay_title.png"

    def clip_mp4(self, i: int) -> Path:
        return self.clips_dir / f"scene_{i}.mp4"

    @property
    def concat_txt(self) -> Path:
        return self.root / "concat.txt"

    @property
    def joined_mp4(self) -> Path:
        return self.root / "joined.mp4"

    @property
    def subtitles_ass(self) -> Path:
        return self.root / "subtitles.ass"

    @property
    def subtitles_srt(self) -> Path:
        return self.root / "subtitles.srt"

    @property
    def final_mp4(self) -> Path:
        return self.root / "final.mp4"

    @property
    def render_json(self) -> Path:
        return self.root / "render.json"

    @property
    def metadata_json(self) -> Path:
        return self.root / "metadata.json"

    @property
    def thumbnail_jpg(self) -> Path:
        return self.root / "thumbnail.jpg"

    @property
    def upload_json(self) -> Path:
        return self.root / "upload.json"

    @property
    def job_log(self) -> Path:
        return self.root / "job.log"

    @property
    def lock_file(self) -> Path:
        return self.root / ".lock"


@dataclass
class JobContext:
    job: Job
    topic: Topic
    cfg: AppConfig
    secrets: Secrets
    repo: Repository
    paths: JobPaths
    llm: LLMProvider
    tts: TTSProvider
    stock: StockProvider | None = None
    dry_run: bool = False
    fmt: FormatSpec = field(init=False)

    def __post_init__(self) -> None:
        self.fmt = self.cfg.formats[self.job.format.value]
