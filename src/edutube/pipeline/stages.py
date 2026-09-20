"""Pipeline stages (LLD §7, LLR-ORC-01).

Six core stages run automatically in order (ScriptStage..MetadataStage). UploadStage
is triggered separately by the CLI `upload` command or `daily` (LLD §7.1).
"""

from __future__ import annotations

import json
import random
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from edutube.content.metadata import build_video_metadata, save_metadata
from edutube.content.reviewer import review_and_rewrite
from edutube.content.script_writer import adjust_length, load_script, save_script, write_script
from edutube.errors import DurationFitError, UploadError
from edutube.logging_setup import get_logger
from edutube.media import composer, ffmpeg, slides, subtitles
from edutube.media.slides import build_theme
from edutube.media.stock import load_assets, save_assets
from edutube.media.thumbnail import make_thumbnail
from edutube.media.tts import save_words
from edutube.models import (
    Job,
    JobStatus,
    RenderInfo,
    SceneAudio,
    SceneVisual,
    VideoFormat,
    VisualType,
    VoiceResult,
)
from edutube.pipeline.context import JobContext
from edutube.publish.quota import QuotaTracker
from edutube.publish.uploader import Uploader, UploadResult

log = get_logger("pipeline.stages")


class Stage(ABC):
    name: ClassVar[str]
    success_status: ClassVar[JobStatus]

    @abstractmethod
    def run(self, ctx: JobContext) -> None: ...

    @abstractmethod
    def is_done(self, ctx: JobContext) -> bool: ...

    def outputs(self, ctx: JobContext) -> list[Path]:
        return []


# ---- serialization helpers -------------------------------------------------


def save_voice(voice: VoiceResult, path: Path) -> None:
    path.write_text(json.dumps(voice.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8")


def load_voice(path: Path) -> VoiceResult:
    return VoiceResult.model_validate_json(path.read_text(encoding="utf-8"))


def save_visuals(visuals: list[SceneVisual], path: Path) -> None:
    path.write_text(
        json.dumps([v.model_dump(mode="json") for v in visuals], indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_visuals(path: Path) -> list[SceneVisual]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [SceneVisual(**v) for v in data]


def save_render_info(info: RenderInfo, path: Path) -> None:
    path.write_text(json.dumps(info.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8")


def load_render_info(path: Path) -> RenderInfo:
    return RenderInfo.model_validate_json(path.read_text(encoding="utf-8"))


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def _parse_pct(rate: str) -> int:
    return int(rate.strip().rstrip("%"))


# ---- stages -----------------------------------------------------------------


class ScriptStage(Stage):
    name = "script"
    success_status = JobStatus.SCRIPTED

    def is_done(self, ctx: JobContext) -> bool:
        return ctx.paths.script.exists()

    def run(self, ctx: JobContext) -> None:
        ctx.paths.ensure()
        script = write_script(ctx.llm, ctx.cfg, ctx.topic, ctx.job.format, log_dir=ctx.paths.llm_dir)
        save_script(script, ctx.paths.script)

    def outputs(self, ctx: JobContext) -> list[Path]:
        return [ctx.paths.script, *ctx.paths.root.glob("script_v*.json")]


class ReviewStage(Stage):
    name = "review"
    success_status = JobStatus.REVIEWED

    def is_done(self, ctx: JobContext) -> bool:
        return ctx.paths.review(1).exists()

    def run(self, ctx: JobContext) -> None:
        script = load_script(ctx.paths.script)
        _script, _review, needs_human = review_and_rewrite(
            ctx.llm, ctx.cfg, script, ctx.paths.root, log_dir=ctx.paths.llm_dir
        )
        if needs_human:
            ctx.repo.update_job(ctx.job.id, needs_human_review=True)
            ctx.job.needs_human_review = True

    def outputs(self, ctx: JobContext) -> list[Path]:
        return list(ctx.paths.root.glob("review_*.json"))


class VoiceStage(Stage):
    name = "voice"
    success_status = JobStatus.VOICED

    def is_done(self, ctx: JobContext) -> bool:
        return ctx.paths.voice_json.exists()

    def run(self, ctx: JobContext) -> None:
        script = load_script(ctx.paths.script)
        spec = ctx.fmt
        voice_cfg = ctx.cfg.tts
        voice_name = voice_cfg.voices.get(ctx.job.language, voice_cfg.voices.get("en", "en-IN-PrabhatNeural"))
        rate = voice_cfg.rate
        scene_audios: list[SceneAudio] = []
        total = 0.0

        for attempt in range(3):
            scene_audios = []
            for scene in script.scenes:
                mp3_path = ctx.paths.scene_mp3(scene.index)
                words = ctx.tts.synthesize(
                    scene.narration, mp3_path, voice=voice_name, rate=rate, pitch=voice_cfg.pitch
                )
                save_words(words, ctx.paths.scene_words(scene.index))
                duration = ffmpeg.probe(mp3_path).duration
                scene_audios.append(SceneAudio(index=scene.index, path=mp3_path, duration=duration, words=words))

            total = sum(a.duration for a in scene_audios) + len(scene_audios) * ctx.cfg.render.scene_padding_s
            if spec.min_s <= total <= spec.max_s:
                break

            if attempt == 0:
                pct_adjust = round((total / spec.target_s - 1) * 100)
                new_pct = _clamp(_parse_pct(rate) + pct_adjust, -15, 15)
                rate = f"{new_pct:+d}%"
                continue

            direction = "Shorten" if total > spec.max_s else "Lengthen"
            script = adjust_length(ctx.llm, ctx.cfg, script, spec, direction, log_dir=ctx.paths.llm_dir)
            save_script(script, ctx.paths.script)
            rate = ctx.cfg.tts.rate
        else:
            raise DurationFitError(f"voice duration {total:.1f}s outside {spec.min_s}-{spec.max_s}s after retries")

        save_voice(VoiceResult(scenes=scene_audios, rate=rate, total_duration=total), ctx.paths.voice_json)

    def outputs(self, ctx: JobContext) -> list[Path]:
        return [ctx.paths.voice_json, *ctx.paths.audio_dir.glob("*")]


class VisualStage(Stage):
    name = "visuals"
    success_status = JobStatus.VISUALS_READY

    def is_done(self, ctx: JobContext) -> bool:
        return ctx.paths.visuals_json.exists()

    def run(self, ctx: JobContext) -> None:
        script = load_script(ctx.paths.script)
        theme = build_theme(ctx.cfg)
        orientation = "portrait" if ctx.job.format == VideoFormat.SHORT else "landscape"

        visuals: list[SceneVisual] = []
        attributions = []
        used_ids: set[int] = set()

        for scene in script.scenes:
            if scene.visual == VisualType.BROLL and ctx.stock is not None:
                result = ctx.stock.fetch_video(
                    scene.broll_query or scene.on_screen_title,
                    orientation=orientation,
                    min_duration=2.0,
                    target_height=ctx.fmt.height,
                    exclude_ids=used_ids,
                    dest_dir=ctx.paths.broll_dir,
                )
                if result is not None:
                    path, attribution = result
                    used_ids.add(attribution.pexels_id)
                    attributions.append(attribution)
                    visuals.append(SceneVisual(index=scene.index, kind="broll", path=path))
                    continue
                log.warning(
                    "no b-roll found for scene %d query=%r; falling back to slide", scene.index, scene.broll_query
                )

            out_path = ctx.paths.slide_png(scene.index)
            slides.render_slide(scene, ctx.job.format, ctx.fmt, theme, out_path, language=ctx.job.language)
            visuals.append(
                SceneVisual(
                    index=scene.index, kind="slide", path=out_path, fallback_used=scene.visual == VisualType.BROLL
                )
            )

        save_visuals(visuals, ctx.paths.visuals_json)
        save_assets(attributions, ctx.paths.assets_json)

        if ctx.job.format == VideoFormat.SHORT:
            overlay = slides.render_title_bar(ctx.topic.title, ctx.fmt, theme)
            overlay.save(ctx.paths.overlay_title, "PNG")

    def outputs(self, ctx: JobContext) -> list[Path]:
        return [
            ctx.paths.visuals_json,
            ctx.paths.assets_json,
            ctx.paths.overlay_title,
            *ctx.paths.slides_dir.glob("*"),
            *ctx.paths.broll_dir.glob("*"),
        ]


def _pick_music(ctx: JobContext) -> Path | None:
    if not ctx.cfg.render.music_enabled:
        return None
    music_dir = ctx.cfg.resolve(ctx.cfg.render.music_dir)
    if not music_dir.exists():
        return None
    tracks = list(music_dir.glob("*.mp3"))
    return random.choice(tracks) if tracks else None


class RenderStage(Stage):
    name = "render"
    success_status = JobStatus.RENDERED

    def is_done(self, ctx: JobContext) -> bool:
        return ctx.paths.final_mp4.exists()

    def run(self, ctx: JobContext) -> None:
        script = load_script(ctx.paths.script)
        voice = load_voice(ctx.paths.voice_json)
        visuals_by_index = {v.index: v for v in load_visuals(ctx.paths.visuals_json)}
        is_short = ctx.job.format == VideoFormat.SHORT

        durations: list[float] = []
        clip_paths: list[Path] = []
        for scene in script.scenes:
            visual = visuals_by_index[scene.index]
            audio_path = ctx.paths.scene_mp3(scene.index)
            clip_path = ctx.paths.clip_mp4(scene.index)
            if visual.kind == "broll":
                duration = composer.render_broll_clip(
                    visual.path, audio_path, clip_path, fmt=ctx.fmt, render_cfg=ctx.cfg.render, is_short=is_short
                )
            else:
                duration = composer.render_slide_clip(
                    visual.path, audio_path, clip_path, fmt=ctx.fmt, render_cfg=ctx.cfg.render
                )
            durations.append(duration)
            clip_paths.append(clip_path)

        scene_starts = composer.compute_scene_starts(durations)
        composer.concat_clips(clip_paths, ctx.paths.concat_txt, ctx.paths.joined_mp4)

        timeline = subtitles.build_timeline(voice, scene_starts)
        if is_short:
            cues = subtitles.chunk_short(timeline)
            ass_content = subtitles.to_ass_short(cues, ctx.fmt, ctx.cfg.brand)
        else:
            cues = subtitles.chunk_long(timeline)
            ass_content = subtitles.to_ass_long(cues, ctx.fmt, ctx.cfg.brand)
        ctx.paths.subtitles_ass.write_text(ass_content, encoding="utf-8")
        ctx.paths.subtitles_srt.write_text(subtitles.to_srt(cues), encoding="utf-8")

        fonts_dir = ctx.cfg.resolve("assets/fonts")
        overlay_path = ctx.paths.overlay_title if is_short and ctx.paths.overlay_title.exists() else None
        music_path = _pick_music(ctx)

        composer.compose_final(
            ctx.paths.joined_mp4,
            ctx.paths.subtitles_ass,
            fonts_dir,
            ctx.paths.final_mp4,
            render_cfg=ctx.cfg.render,
            overlay_title_path=overlay_path,
            music_path=music_path,
        )

        info = composer.validate_render(ctx.paths.final_mp4, ctx.fmt)
        lufs = ffmpeg.loudness(ctx.paths.final_mp4)
        target = ctx.cfg.render.target_lufs
        if not (target - 1 <= lufs <= target + 1):
            log.warning("final loudness %.1f LUFS outside target %d +/-1", lufs, target)

        save_render_info(
            RenderInfo(
                path=ctx.paths.final_mp4,
                duration=info.duration,
                width=ctx.fmt.width,
                height=ctx.fmt.height,
                lufs=lufs,
                scene_starts=scene_starts,
            ),
            ctx.paths.render_json,
        )

    def outputs(self, ctx: JobContext) -> list[Path]:
        return [
            ctx.paths.final_mp4,
            ctx.paths.render_json,
            ctx.paths.subtitles_ass,
            ctx.paths.subtitles_srt,
            ctx.paths.concat_txt,
            ctx.paths.joined_mp4,
            *ctx.paths.clips_dir.glob("*"),
        ]


class MetadataStage(Stage):
    name = "metadata"
    success_status = JobStatus.METADATA_READY

    def is_done(self, ctx: JobContext) -> bool:
        return ctx.paths.metadata_json.exists()

    def run(self, ctx: JobContext) -> None:
        script = load_script(ctx.paths.script)
        render_info = load_render_info(ctx.paths.render_json)
        attributions = load_assets(ctx.paths.assets_json)
        meta = build_video_metadata(
            ctx.llm, ctx.cfg, script, render_info, attributions, log_dir=ctx.paths.llm_dir
        )
        save_metadata(meta, ctx.paths.metadata_json)

        if ctx.job.format == VideoFormat.LONG:
            theme = build_theme(ctx.cfg)
            visuals = load_visuals(ctx.paths.visuals_json)
            first_broll = next((v.path for v in visuals if v.kind == "broll"), None)
            make_thumbnail(meta, theme, ctx.paths.thumbnail_jpg, first_broll, ctx.paths.root)

    def outputs(self, ctx: JobContext) -> list[Path]:
        return [ctx.paths.metadata_json, ctx.paths.thumbnail_jpg]


PIPELINE: list[Stage] = [
    ScriptStage(),
    ReviewStage(),
    VoiceStage(),
    VisualStage(),
    RenderStage(),
    MetadataStage(),
]

STAGE_BY_NAME: dict[str, Stage] = {s.name: s for s in PIPELINE}


class UploadStage(Stage):
    """Not part of PIPELINE; triggered by `edutube upload` / `daily` (LLD §7.1)."""

    name = "upload"
    success_status = JobStatus.UPLOADED

    def is_done(self, ctx: JobContext) -> bool:
        return ctx.repo.get_upload(ctx.job.id) is not None

    def run(self, ctx: JobContext) -> None:
        if ctx.job.status != JobStatus.APPROVED and not ctx.dry_run:
            raise UploadError(f"Job {ctx.job.id} is not APPROVED (status={ctx.job.status})")

        from edutube.content.metadata import VideoMetadata

        meta = VideoMetadata.model_validate_json(ctx.paths.metadata_json.read_text(encoding="utf-8"))
        quota = QuotaTracker(ctx.repo, ctx.cfg.quota)
        uploader = Uploader(ctx.repo, quota, ctx.cfg, ctx.cfg.resolve(ctx.cfg.paths.secrets) / "token.json")

        thumbnail = ctx.paths.thumbnail_jpg if ctx.paths.thumbnail_jpg.exists() else None
        srt = ctx.paths.subtitles_srt if ctx.paths.subtitles_srt.exists() else None

        result: UploadResult = uploader.upload(
            ctx.job, meta, ctx.paths.final_mp4, thumbnail=thumbnail, srt=srt, dry_run=ctx.dry_run
        )
        if result.dry_run or result.already_uploaded:
            return
        ctx.paths.upload_json.write_text(
            json.dumps({"video_id": result.video_id, "url": result.url}, indent=2), encoding="utf-8"
        )
        ctx.repo.update_job(ctx.job.id, status=JobStatus.UPLOADED)

    def outputs(self, ctx: JobContext) -> list[Path]:
        return [ctx.paths.upload_json]


def job_display(job: Job) -> str:
    return f"{job.id} [{job.status}]"
