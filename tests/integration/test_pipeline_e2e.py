"""End-to-end pipeline integration tests with fake LLM/TTS + real FFmpeg (LLD §13)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from edutube.content.metadata import build_video_metadata
from edutube.db import Repository
from edutube.llm.fake_provider import FakeLLMProvider
from edutube.media.ffmpeg import probe
from edutube.media.tts import FakeTTSProvider
from edutube.models import JobStatus, Review, Scores, Script, Topic, VideoFormat, VideoMetadata
from edutube.pipeline import orchestrator

pytestmark = pytest.mark.ffmpeg


def _high_review() -> Review:
    return Review(
        scores=Scores(accuracy=9, clarity=9, hook=9, beginner_friendly=9, structure=9),
        issues=[],
        human_check_claims=[],
        rewrite_instructions="",
    )


def _fake_metadata() -> VideoMetadata:
    return VideoMetadata(
        title="What is a Neural Network?",
        description_intro="A quick, friendly look at how neural networks work.",
        key_points=["Neurons and layers", "Weights and training", "Why it matters"],
        tags=["ai", "neural network", "machine learning"],
        hashtags=["#AI", "#MachineLearning", "#Tech"],
        thumbnail_text="NEURAL NETWORKS",
    )


def _install_fakes(monkeypatch, script: Script) -> FakeLLMProvider:
    fake_llm = FakeLLMProvider()
    prompt = "script_short.md" if script.format == VideoFormat.SHORT else "script_long.md"
    fake_llm.register(prompt, lambda: script)
    fake_llm.register("review.md", _high_review)
    fake_llm.register("metadata.md", _fake_metadata)

    monkeypatch.setattr(orchestrator, "_make_llm", lambda cfg: fake_llm)
    monkeypatch.setattr(orchestrator, "_make_tts", lambda cfg: FakeTTSProvider())
    monkeypatch.setattr(orchestrator, "_make_stock", lambda cfg, repo, secrets: None)
    return fake_llm


def _run_e2e(cfg, repo: Repository, monkeypatch, script: Script, fmt: VideoFormat):
    cfg.render.preset = "ultrafast"
    cfg.render.ken_burns = False
    cfg.render.music_enabled = False
    _install_fakes(monkeypatch, script)

    topic = Topic(title=script.topic_title, created_at=datetime.now(UTC))
    topic.id = repo.add_topic(topic)

    from edutube.config import Secrets

    secrets = Secrets()

    job = orchestrator.create_job(repo, topic, fmt, "en")
    result = orchestrator.run_job(job.id, cfg, secrets, repo)
    return job, result


@pytest.mark.ffmpeg
def test_short_pipeline_end_to_end(cfg, repo: Repository, monkeypatch, script_short: Script):
    job, result = _run_e2e(cfg, repo, monkeypatch, script_short, VideoFormat.SHORT)

    assert result.status == JobStatus.AWAITING_APPROVAL

    job_dir = cfg.resolve(cfg.paths.workspace) / "jobs" / job.id
    final_mp4 = job_dir / "final.mp4"
    assert final_mp4.exists()

    info = probe(final_mp4)
    v = info.video_streams[0]
    assert (v.width, v.height) == (1080, 1920)
    assert 29 <= info.duration <= 41

    assert (job_dir / "metadata.json").exists()
    meta = json.loads((job_dir / "metadata.json").read_text(encoding="utf-8"))
    assert meta["title"].endswith("#Shorts")


@pytest.mark.ffmpeg
def test_long_pipeline_end_to_end(cfg, repo: Repository, monkeypatch, script_long: Script):
    job, result = _run_e2e(cfg, repo, monkeypatch, script_long, VideoFormat.LONG)

    assert result.status == JobStatus.AWAITING_APPROVAL
    job_dir = cfg.resolve(cfg.paths.workspace) / "jobs" / job.id
    final_mp4 = job_dir / "final.mp4"
    assert final_mp4.exists()

    info = probe(final_mp4)
    v = info.video_streams[0]
    assert (v.width, v.height) == (1920, 1080)
    assert 239 <= info.duration <= 301

    thumb = job_dir / "thumbnail.jpg"
    assert thumb.exists()
    assert thumb.stat().st_size < 2 * 1024 * 1024

    meta = json.loads((job_dir / "metadata.json").read_text(encoding="utf-8"))
    assert len(meta["chapters"]) >= 3


@pytest.mark.ffmpeg
def test_resume_is_idempotent_and_skips_completed_stages(cfg, repo: Repository, monkeypatch, script_short: Script):
    from edutube.config import Secrets

    cfg.render.preset = "ultrafast"
    cfg.render.ken_burns = False
    cfg.render.music_enabled = False
    fake_llm = _install_fakes(monkeypatch, script_short)

    topic = Topic(title=script_short.topic_title, created_at=datetime.now(UTC))
    topic.id = repo.add_topic(topic)
    job = orchestrator.create_job(repo, topic, VideoFormat.SHORT, "en")

    orchestrator.run_job(job.id, cfg, Secrets(), repo)
    script_calls_after_first_run = len([c for c in fake_llm.calls if c["prompt_name"] == "script_short.md"])
    assert script_calls_after_first_run == 1

    # Resuming a fully-completed job should skip every stage (idempotent, LLR-ORC-02).
    result = orchestrator.resume(job.id, cfg, Secrets(), repo)
    assert result.status == JobStatus.AWAITING_APPROVAL
    assert len([c for c in fake_llm.calls if c["prompt_name"] == "script_short.md"]) == 1

    # --from-stage voice should clear voice/visuals/render/metadata but NOT touch the script.
    result = orchestrator.resume(job.id, cfg, Secrets(), repo, from_stage="voice")
    assert result.status == JobStatus.AWAITING_APPROVAL
    assert len([c for c in fake_llm.calls if c["prompt_name"] == "script_short.md"]) == 1
    job_dir = cfg.resolve(cfg.paths.workspace) / "jobs" / job.id
    assert (job_dir / "final.mp4").exists()


@pytest.mark.ffmpeg
def test_run_daily_creates_jobs_without_uploading(cfg, repo: Repository, monkeypatch, script_short: Script):
    from edutube.config import Secrets

    cfg.render.preset = "ultrafast"
    cfg.render.ken_burns = False
    cfg.render.music_enabled = False
    cfg.schedule.shorts_per_day = 1
    cfg.schedule.longs_per_day = 0
    _install_fakes(monkeypatch, script_short)

    topic = Topic(title=script_short.topic_title, created_at=datetime.now(UTC))
    repo.add_topic(topic)

    result = orchestrator.run_daily(cfg, Secrets(), repo, upload=False)
    assert len(result["created"]) == 1
    assert result["failed"] == []
    assert result["uploaded"] == []
    job = repo.get_job(result["created"][0])
    assert job.status == JobStatus.AWAITING_APPROVAL


def test_build_video_metadata_smoke(cfg, script_long: Script):
    from edutube.models import RenderInfo

    fake_llm = FakeLLMProvider()
    fake_llm.register("metadata.md", _fake_metadata)
    render_info = RenderInfo(
        path="final.mp4", duration=260.0, width=1920, height=1080, lufs=-14.0,
        scene_starts=[0.0, 30.0, 60.0, 90.0, 120.0, 150.0, 180.0, 210.0, 240.0],
    )
    meta = build_video_metadata(fake_llm, cfg, script_long, render_info, [])
    assert meta.description
    assert len(meta.chapters) >= 3
