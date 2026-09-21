"""VoiceStage duration-fit loop (LLR-TTS-04) with a stub TTS and patched ffprobe."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from edutube.config import AppConfig, Secrets
from edutube.db import Repository
from edutube.errors import DurationFitError
from edutube.llm.fake_provider import FakeLLMProvider
from edutube.media import ffmpeg
from edutube.media.tts import TTSProvider
from edutube.models import Job, JobStatus, Scene, SceneRole, Script, Topic, VideoFormat, VisualType, Word
from edutube.pipeline.context import JobContext, JobPaths
from edutube.pipeline.stages import VoiceStage


class PacedTTS(TTSProvider):
    """Speaks at a fixed seconds-per-word pace, faster when the rate is positive."""

    def __init__(self, sec_per_word: float) -> None:
        self.sec_per_word = sec_per_word
        self.rates: list[str] = []

    def synthesize(self, text: str, out_mp3: Path, *, voice: str, rate: str, pitch: str) -> list[Word]:
        self.rates.append(rate)
        pct = int(rate.rstrip("%"))
        per_word = self.sec_per_word / (1 + pct / 100)
        words = text.split()
        out_mp3.parent.mkdir(parents=True, exist_ok=True)
        out_mp3.write_text(str(len(words) * per_word))
        return [Word(word=w, start=i * per_word, end=(i + 1) * per_word) for i, w in enumerate(words)]


def _script(words_per_scene: int) -> Script:
    def scene(i: int, role: SceneRole) -> Scene:
        return Scene(
            index=i, role=role, visual=VisualType.TITLE,
            narration=" ".join(["word"] * words_per_scene), on_screen_title="T",
        )

    return Script(
        topic_title="t", format=VideoFormat.SHORT, language="en", title="T", hook="H",
        scenes=[scene(0, SceneRole.HOOK), scene(1, SceneRole.CONTENT), scene(2, SceneRole.CTA)],
    )


@pytest.fixture()
def ctx_factory(cfg: AppConfig, repo: Repository, monkeypatch, tmp_root: Path):
    monkeypatch.setattr(
        ffmpeg, "probe", lambda p: ffmpeg.ProbeInfo(duration=float(Path(p).read_text()), streams=[])
    )

    def make(tts: TTSProvider, llm: FakeLLMProvider, script: Script) -> JobContext:
        from edutube.content.script_writer import save_script

        now = datetime.now(UTC)
        topic = Topic(title="What is RAG?", created_at=now)
        topic.id = repo.add_topic(topic)
        job = Job(
            id="job1", topic_id=topic.id, format=VideoFormat.SHORT, language="en",
            status=JobStatus.REVIEWED, created_at=now, updated_at=now,
        )
        repo.create_job(job)
        paths = JobPaths(tmp_root / "workspace" / "jobs" / "job1")
        paths.ensure()
        save_script(script, paths.script)
        return JobContext(
            job=job, topic=topic, cfg=cfg, secrets=Secrets(), repo=repo, paths=paths, llm=llm, tts=tts
        )

    return make


def test_in_range_first_pass_needs_no_adjustment(ctx_factory):
    tts = PacedTTS(0.4)  # 3 scenes * 30 words * 0.4s = 36s (+0.75 padding) -> in 30-40
    ctx = ctx_factory(tts, FakeLLMProvider(), _script(30))
    VoiceStage().run(ctx)
    assert tts.rates.count("+0%") == 3 and len(tts.rates) == 3
    assert ctx.paths.voice_json.exists()


def test_rate_speedup_alone_can_fix_a_slightly_long_script(ctx_factory):
    tts = PacedTTS(0.5)  # 3*30*0.5 = 45s (+0.75) -> too long; +15% -> ~39.5s
    ctx = ctx_factory(tts, FakeLLMProvider(), _script(30))
    VoiceStage().run(ctx)
    assert tts.rates[-1] == "+15%"
    assert "adjust_length.md" not in [c["prompt_name"] for c in ctx.llm.calls]  # type: ignore[attr-defined]


def test_adjust_length_result_is_resynthesized_and_keeps_rate(ctx_factory):
    tts = PacedTTS(0.8)  # 72s: rate alone (+15%) cannot fix it
    llm = FakeLLMProvider()
    llm.register("adjust_length.md", lambda: _script(15))  # 3*15*0.8/1.15 = 31.3s + 0.75 -> in range
    ctx = ctx_factory(tts, llm, _script(30))
    VoiceStage().run(ctx)
    assert len([c for c in llm.calls if c["prompt_name"] == "adjust_length.md"]) == 1
    assert tts.rates[-1] == "+15%"  # speed-up is kept after shortening, not reset
    assert ctx.paths.voice_json.exists()


def test_raises_after_two_adjustments_and_never_wastes_a_pass(ctx_factory):
    tts = PacedTTS(2.0)
    llm = FakeLLMProvider()
    llm.register("adjust_length.md", lambda: _script(29))  # barely shorter, still far too long
    ctx = ctx_factory(tts, llm, _script(30))
    with pytest.raises(DurationFitError):
        VoiceStage().run(ctx)
    assert len([c for c in llm.calls if c["prompt_name"] == "adjust_length.md"]) == 2
    # 1 initial + 1 rate retry + 2 post-adjust re-syntheses = 4 passes of 3 scenes
    assert len(tts.rates) == 12
