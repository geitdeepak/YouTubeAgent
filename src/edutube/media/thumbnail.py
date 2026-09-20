"""Thumbnail generation (LLD §8.7, LLR-THB-01..03)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from edutube.media import ffmpeg
from edutube.media.slides import SlideTheme, draw_gradient, fit_text, hex_to_rgb
from edutube.models import VideoMetadata

THUMB_W = 1280
THUMB_H = 720
MAX_BYTES = 2 * 1024 * 1024


def _extract_frame(video_path: Path, out_png: Path, at_fraction: float = 0.3) -> bool:
    try:
        duration = ffmpeg.probe(video_path).duration
    except Exception:  # noqa: BLE001
        return False
    ts = max(duration * at_fraction, 0.0)
    try:
        ffmpeg.run(
            [
                ffmpeg.ffmpeg_bin(),
                "-y",
                "-ss",
                str(ts),
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(out_png),
            ]
        )
    except Exception:  # noqa: BLE001
        return False
    return out_png.exists()


def _cover_resize(img: Image.Image, w: int, h: int) -> Image.Image:
    src_ratio = img.width / img.height
    dst_ratio = w / h
    if src_ratio > dst_ratio:
        new_h = h
        new_w = round(h * src_ratio)
    else:
        new_w = w
        new_h = round(w / src_ratio)
    resized = img.resize((new_w, new_h))
    left = (new_w - w) // 2
    top = (new_h - h) // 2
    return resized.crop((left, top, left + w, top + h))


def make_thumbnail(
    meta: VideoMetadata, theme: SlideTheme, out_path: Path, first_broll: Path | None, tmp_dir: Path
) -> Path:
    """LLR-THB-01..03: 1280x720 JPG <2MB, dark left panel, auto-fit bold text."""
    bg: Image.Image
    frame_path = tmp_dir / "thumb_frame.png"
    if first_broll is not None and _extract_frame(first_broll, frame_path):
        bg = Image.open(frame_path).convert("RGB")
        bg = _cover_resize(bg, THUMB_W, THUMB_H)
    else:
        bg = Image.new("RGB", (THUMB_W, THUMB_H))
        draw_gradient(bg, theme.background, theme.primary)

    overlay = Image.new("RGBA", (THUMB_W, THUMB_H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    panel_w = round(THUMB_W * 0.6)
    for x in range(panel_w):
        alpha = int(170 * (1 - x / panel_w * 0.3))
        odraw.line([(x, 0), (x, THUMB_H)], fill=(0, 0, 0, alpha))
    bg = Image.alpha_composite(bg.convert("RGBA"), overlay)

    draw = ImageDraw.Draw(bg)
    words = meta.thumbnail_text.upper().split()[:5]
    text = "\n".join(words) if len(" ".join(words)) > 20 else " ".join(words)
    font, lines = fit_text(draw, text.replace("\n", " "), theme.font_bold, panel_w * 0.85, THUMB_H * 0.72, 150, 80)

    keyword_idx = max(range(len(words)), key=lambda i: len(words[i])) if words else -1
    keyword = words[keyword_idx] if keyword_idx >= 0 else ""
    text_y: float = THUMB_H * 0.14
    for line in lines:
        text_x: float = THUMB_W * 0.06
        for word in line.split():
            color = hex_to_rgb(theme.accent) if word == keyword else hex_to_rgb(theme.text)
            draw.text((text_x, text_y), word, font=font, fill=color, stroke_width=8, stroke_fill=(0, 0, 0))
            text_x += draw.textlength(word + " ", font=font)
        text_y += font.size * 1.2

    if theme.logo and theme.logo.exists():
        logo = Image.open(theme.logo).convert("RGBA")
        target_w = 140
        scale = target_w / logo.width
        logo = logo.resize((target_w, max(1, round(logo.height * scale))))
        bg.paste(logo, (30, THUMB_H - logo.height - 30), logo)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    quality = 90
    rgb = bg.convert("RGB")
    rgb.save(out_path, "JPEG", quality=quality)
    while out_path.stat().st_size > MAX_BYTES and quality > 30:
        quality -= 10
        rgb.save(out_path, "JPEG", quality=quality)
    return out_path
