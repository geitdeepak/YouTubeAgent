"""Scene clip rendering + final composition with FFmpeg (LLD §8.6, LLR-CMP-01..09)."""

from __future__ import annotations

import math
from pathlib import Path

from edutube.config import FormatSpec, RenderCfg
from edutube.errors import RenderValidationError
from edutube.logging_setup import get_logger
from edutube.media.ffmpeg import ProbeInfo, ff_filter_path, ffmpeg_bin, probe, run

log = get_logger("media.composer")


def encode_args(cfg: RenderCfg) -> list[str]:
    return [
        "-c:v",
        "libx264",
        "-preset",
        cfg.preset,
        "-crf",
        str(cfg.crf),
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(cfg.fps),
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-ac",
        "2",
    ]


def render_slide_clip(
    image_path: Path, audio_path: Path, out_path: Path, *, fmt: FormatSpec, render_cfg: RenderCfg
) -> float:
    """Slide scene clip with optional Ken Burns zoom (LLR-CMP-02, LLR-CMP-03)."""
    duration = probe(audio_path).duration + render_cfg.scene_padding_s
    fade_out_start = max(duration - render_cfg.fade_s, 0.0)
    frames = math.ceil(duration * render_cfg.fps)

    if render_cfg.ken_burns:
        vf = (
            f"[0:v]scale={fmt.width * 2}:{fmt.height * 2},"
            f"zoompan=z='min(zoom+0.0005,1.05)':d={frames}:s={fmt.width}x{fmt.height}:fps={render_cfg.fps},"
            f"fade=t=in:st=0:d={render_cfg.fade_s},fade=t=out:st={fade_out_start}:d={render_cfg.fade_s}[v]"
        )
    else:
        vf = (
            f"[0:v]scale={fmt.width}:{fmt.height},"
            f"fade=t=in:st=0:d={render_cfg.fade_s},fade=t=out:st={fade_out_start}:d={render_cfg.fade_s}[v]"
        )
    filter_complex = f"{vf};[1:a]apad=pad_dur={render_cfg.scene_padding_s}[a]"

    args = [
        ffmpeg_bin(),
        "-y",
        "-loop",
        "1",
        "-framerate",
        str(render_cfg.fps),
        "-i",
        str(image_path),
        "-i",
        str(audio_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-t",
        str(duration),
        *encode_args(render_cfg),
        str(out_path),
    ]
    run(args)
    return duration


def render_broll_clip(
    video_path: Path,
    audio_path: Path,
    out_path: Path,
    *,
    fmt: FormatSpec,
    render_cfg: RenderCfg,
    is_short: bool,
) -> float:
    """B-roll scene clip: cover-crop, Short darkened (LLR-CMP-03)."""
    duration = probe(audio_path).duration + render_cfg.scene_padding_s
    fade_out_start = max(duration - render_cfg.fade_s, 0.0)

    vf = (
        f"scale={fmt.width}:{fmt.height}:force_original_aspect_ratio=increase,"
        f"crop={fmt.width}:{fmt.height},setsar=1,fps={render_cfg.fps}"
    )
    if is_short:
        vf += ",eq=brightness=-0.25:saturation=0.9"
    vf += f",fade=t=in:st=0:d={render_cfg.fade_s},fade=t=out:st={fade_out_start}:d={render_cfg.fade_s}"
    filter_complex = f"[0:v]{vf}[v];[1:a]apad=pad_dur={render_cfg.scene_padding_s}[a]"

    args = [
        ffmpeg_bin(),
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-t",
        str(duration),
        *encode_args(render_cfg),
        str(out_path),
    ]
    run(args)
    return duration


def _concat_escape(p: Path) -> str:
    s = str(p.resolve()).replace("\\", "/")
    return s.replace("'", "'\\''")


def concat_clips(clip_paths: list[Path], concat_txt_path: Path, joined_path: Path) -> None:
    """Concat identically-encoded clips with stream copy (LLR-CMP-04)."""
    lines = [f"file '{_concat_escape(p)}'" for p in clip_paths]
    concat_txt_path.parent.mkdir(parents=True, exist_ok=True)
    concat_txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    run([ffmpeg_bin(), "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt_path), "-c", "copy", str(joined_path)])


def compose_final(
    joined_path: Path,
    subtitles_ass_path: Path,
    fonts_dir: Path,
    out_path: Path,
    *,
    render_cfg: RenderCfg,
    overlay_title_path: Path | None = None,
    music_path: Path | None = None,
) -> None:
    """Burn captions, optional overlay + ducked music, loudnorm, faststart (LLR-CMP-06, LLR-CMP-07)."""
    inputs: list[str] = ["-i", str(joined_path)]
    next_idx = 1
    overlay_idx: int | None = None
    music_idx: int | None = None

    if overlay_title_path is not None:
        inputs += ["-i", str(overlay_title_path)]
        overlay_idx, next_idx = next_idx, next_idx + 1
    if music_path is not None and render_cfg.music_enabled:
        inputs += ["-stream_loop", "-1", "-i", str(music_path)]
        music_idx, next_idx = next_idx, next_idx + 1

    filter_parts: list[str] = []
    video_label = "0:v"
    if overlay_idx is not None:
        filter_parts.append(f"[0:v][{overlay_idx}:v]overlay=0:0[vo]")
        video_label = "vo"

    ass_path = ff_filter_path(subtitles_ass_path)
    fonts_path = ff_filter_path(fonts_dir)
    filter_parts.append(f"[{video_label}]ass='{ass_path}':fontsdir='{fonts_path}'[v]")

    lufs = render_cfg.target_lufs
    if music_idx is not None:
        filter_parts.append(f"[{music_idx}:a]volume={render_cfg.music_volume_db}dB[m]")
        filter_parts.append("[m][0:a]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=300[md]")
        filter_parts.append(f"[0:a][md]amix=inputs=2:duration=first:normalize=0,loudnorm=I={lufs}:TP=-1.5:LRA=11[a]")
    else:
        filter_parts.append(f"[0:a]loudnorm=I={lufs}:TP=-1.5:LRA=11[a]")

    filter_complex = ";".join(filter_parts)
    args = (
        [ffmpeg_bin(), "-y", *inputs, "-filter_complex", filter_complex, "-map", "[v]", "-map", "[a]"]
        + encode_args(render_cfg)
        + ["-movflags", "+faststart", str(out_path)]
    )
    run(args)


def compute_scene_starts(durations: list[float]) -> list[float]:
    starts: list[float] = []
    total = 0.0
    for d in durations:
        starts.append(total)
        total += d
    return starts


def validate_render(path: Path, spec: FormatSpec) -> ProbeInfo:
    """ffprobe validation: resolution, duration range, 1 video + 1 audio stream (LLR-CMP-08)."""
    info = probe(path)
    video = info.video_streams
    audio = info.audio_streams
    if len(video) != 1 or len(audio) != 1:
        raise RenderValidationError(
            f"{path.name}: expected 1 video + 1 audio stream, got {len(video)}v/{len(audio)}a"
        )
    v = video[0]
    if v.width != spec.width or v.height != spec.height:
        raise RenderValidationError(
            f"{path.name}: resolution {v.width}x{v.height} != expected {spec.width}x{spec.height}"
        )
    if not (spec.min_s - 1 <= info.duration <= spec.max_s + 1):
        raise RenderValidationError(
            f"{path.name}: duration {info.duration:.1f}s outside {spec.min_s}-{spec.max_s}s (±1s)"
        )
    return info
