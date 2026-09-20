"""Composer tests against real FFmpeg (LLD §8.6, LLR-CMP-01..09)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from edutube.config import FormatSpec, RenderCfg
from edutube.errors import RenderValidationError
from edutube.media import composer, ffmpeg

pytestmark = pytest.mark.ffmpeg


@pytest.fixture()
def render_cfg() -> RenderCfg:
    return RenderCfg(preset="ultrafast", ken_burns=False, music_enabled=False)


@pytest.fixture()
def fmt() -> FormatSpec:
    return FormatSpec(width=320, height=240, min_s=1, max_s=10, min_words=1, max_words=100)


def _make_sine_audio(path: Path, duration: float = 2.0) -> None:
    ffmpeg.run(
        [
            ffmpeg.ffmpeg_bin(), "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
            "-c:a", "libmp3lame", "-b:a", "128k", str(path),
        ]
    )


def _make_test_video(path: Path, duration: float = 3.0, w: int = 640, h: int = 480) -> None:
    ffmpeg.run(
        [
            ffmpeg.ffmpeg_bin(), "-y", "-f", "lavfi", "-i", f"testsrc=size={w}x{h}:rate=30:duration={duration}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ]
    )


def test_render_slide_clip_produces_correct_duration_and_resolution(tmp_path: Path, render_cfg, fmt):
    img_path = tmp_path / "slide.png"
    Image.new("RGB", (fmt.width, fmt.height), (10, 20, 30)).save(img_path)
    audio_path = tmp_path / "audio.mp3"
    _make_sine_audio(audio_path, duration=2.0)

    out_path = tmp_path / "clip.mp4"
    duration = composer.render_slide_clip(img_path, audio_path, out_path, fmt=fmt, render_cfg=render_cfg)

    assert out_path.exists()
    info = ffmpeg.probe(out_path)
    assert abs(info.duration - duration) < 0.3
    v = info.video_streams[0]
    assert (v.width, v.height) == (fmt.width, fmt.height)
    assert len(info.audio_streams) == 1


def test_render_broll_clip_darkens_for_short(tmp_path: Path, render_cfg, fmt):
    video_path = tmp_path / "broll_src.mp4"
    _make_test_video(video_path, duration=3.0)
    audio_path = tmp_path / "audio.mp3"
    _make_sine_audio(audio_path, duration=1.5)

    out_path = tmp_path / "broll_clip.mp4"
    duration = composer.render_broll_clip(
        video_path, audio_path, out_path, fmt=fmt, render_cfg=render_cfg, is_short=True
    )

    assert out_path.exists()
    info = ffmpeg.probe(out_path)
    assert abs(info.duration - duration) < 0.3
    v = info.video_streams[0]
    assert (v.width, v.height) == (fmt.width, fmt.height)


def test_render_broll_clip_loops_short_source_to_cover_duration(tmp_path: Path, render_cfg, fmt):
    video_path = tmp_path / "broll_src.mp4"
    _make_test_video(video_path, duration=1.0)  # shorter than the target duration
    audio_path = tmp_path / "audio.mp3"
    _make_sine_audio(audio_path, duration=4.0)  # forces looping to cover 4s+

    out_path = tmp_path / "broll_clip.mp4"
    duration = composer.render_broll_clip(
        video_path, audio_path, out_path, fmt=fmt, render_cfg=render_cfg, is_short=False
    )
    info = ffmpeg.probe(out_path)
    assert abs(info.duration - duration) < 0.3
    assert duration > 1.0


def test_concat_clips_joins_multiple_clips(tmp_path: Path, render_cfg, fmt):
    img_path = tmp_path / "slide.png"
    Image.new("RGB", (fmt.width, fmt.height), (5, 5, 5)).save(img_path)

    clip_paths = []
    total_expected = 0.0
    for i in range(2):
        audio_path = tmp_path / f"audio_{i}.mp3"
        _make_sine_audio(audio_path, duration=1.0)
        clip_path = tmp_path / f"clip_{i}.mp4"
        d = composer.render_slide_clip(img_path, audio_path, clip_path, fmt=fmt, render_cfg=render_cfg)
        total_expected += d
        clip_paths.append(clip_path)

    joined_path = tmp_path / "joined.mp4"
    composer.concat_clips(clip_paths, tmp_path / "concat.txt", joined_path)

    assert joined_path.exists()
    info = ffmpeg.probe(joined_path)
    assert abs(info.duration - total_expected) < 0.5


def test_compose_final_burns_subtitles_and_normalizes_loudness(tmp_path: Path, render_cfg, fmt):
    img_path = tmp_path / "slide.png"
    Image.new("RGB", (fmt.width, fmt.height), (5, 5, 5)).save(img_path)
    audio_path = tmp_path / "audio.mp3"
    _make_sine_audio(audio_path, duration=2.0)
    clip_path = tmp_path / "clip.mp4"
    composer.render_slide_clip(img_path, audio_path, clip_path, fmt=fmt, render_cfg=render_cfg)

    joined_path = tmp_path / "joined.mp4"
    composer.concat_clips([clip_path], tmp_path / "concat.txt", joined_path)

    ass_path = tmp_path / "subtitles.ass"
    ass_path.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 320\nPlayResY: 240\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
        "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Cap,Arial,20,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,2,2,5,10,10,10,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:00.00,0:00:02.00,Cap,,0,0,0,,HELLO\n",
        encoding="utf-8",
    )
    fonts_dir = Path(__file__).parent.parent.parent / "assets" / "fonts"

    out_path = tmp_path / "final.mp4"
    composer.compose_final(joined_path, ass_path, fonts_dir, out_path, render_cfg=render_cfg)

    assert out_path.exists()
    info = ffmpeg.probe(out_path)
    assert len(info.video_streams) == 1
    assert len(info.audio_streams) == 1
    lufs = ffmpeg.loudness(out_path)
    assert -16 <= lufs <= -12  # target -14 LUFS +-1, generous tolerance for a short clip


def test_validate_render_rejects_wrong_resolution(tmp_path: Path, render_cfg, fmt):
    img_path = tmp_path / "slide.png"
    Image.new("RGB", (100, 100), (5, 5, 5)).save(img_path)  # wrong size on purpose
    audio_path = tmp_path / "audio.mp3"
    _make_sine_audio(audio_path, duration=1.0)
    clip_path = tmp_path / "clip.mp4"

    wrong_fmt = FormatSpec(width=100, height=100, min_s=0, max_s=10, min_words=1, max_words=100)
    composer.render_slide_clip(img_path, audio_path, clip_path, fmt=wrong_fmt, render_cfg=render_cfg)

    with pytest.raises(RenderValidationError, match="resolution"):
        composer.validate_render(clip_path, fmt)  # expects 320x240, actual is 100x100


def test_compute_scene_starts():
    assert composer.compute_scene_starts([1.0, 2.5, 3.0]) == [0.0, 1.0, 3.5]
