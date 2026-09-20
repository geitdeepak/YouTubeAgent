"""Slide rendering with Pillow (LLD §8.3, LLR-SLD-01..06)."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from edutube.config import AppConfig, FormatSpec
from edutube.logging_setup import get_logger
from edutube.models import Scene, VideoFormat, VisualType

log = get_logger("media.slides")

_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    key = (str(path), size)
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = ImageFont.truetype(str(path), size)
    return _FONT_CACHE[key]


def hex_to_rgb(hex_color: str, alpha: int | None = None) -> tuple[int, ...]:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (r, g, b, alpha) if alpha is not None else (r, g, b)


@dataclass
class SlideTheme:
    primary: str
    accent: str
    background: str
    text: str
    font_bold: Path
    font_regular: Path
    font_mono: Path
    font_hindi: Path
    logo: Path | None


def build_theme(cfg: AppConfig) -> SlideTheme:
    brand = cfg.brand
    logo_path = cfg.resolve(brand.logo)
    return SlideTheme(
        primary=brand.primary,
        accent=brand.accent,
        background=brand.background,
        text=brand.text,
        font_bold=cfg.resolve(brand.font_bold),
        font_regular=cfg.resolve(brand.font_regular),
        font_mono=cfg.resolve(brand.font_mono),
        font_hindi=cfg.resolve(brand.font_hindi),
        logo=logo_path if logo_path.exists() else None,
    )


def _body_font(theme: SlideTheme, language: str) -> Path:
    return theme.font_hindi if language == "hi" else theme.font_regular


def wrap_lines(text: str, font: ImageFont.FreeTypeFont, max_w: float, draw: ImageDraw.ImageDraw) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for w in words:
        candidate = f"{current} {w}".strip()
        width = draw.textlength(candidate, font=font)
        if width <= max_w or not current:
            current = candidate
        else:
            lines.append(current)
            current = w
    if current:
        lines.append(current)
    return lines


def fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: Path,
    max_w: float,
    max_h: float,
    start_size: int,
    min_size: int = 24,
    line_spacing: float = 1.25,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Auto-fit text: shrink font 4px at a time; wrap + truncate at min size (LLR-SLD-03)."""
    size = start_size
    font = _font(font_path, size)
    lines = wrap_lines(text, font, max_w, draw)
    while size > min_size:
        line_h = (font.getbbox("Ag")[3] - font.getbbox("Ag")[1]) * line_spacing
        if line_h * len(lines) <= max_h:
            return font, lines
        size -= 4
        font = _font(font_path, size)
        lines = wrap_lines(text, font, max_w, draw)

    font = _font(font_path, min_size)
    lines = wrap_lines(text, font, max_w, draw)
    line_h = (font.getbbox("Ag")[3] - font.getbbox("Ag")[1]) * line_spacing
    max_lines = max(1, int(max_h / line_h)) if line_h else len(lines)
    if len(lines) > max_lines:
        log.warning("slide text truncated to fit: %r", text)
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip() + "…"
    return font, lines


def draw_gradient(img: Image.Image, top_hex: str, bottom_hex: str) -> None:
    w, h = img.size
    top = hex_to_rgb(top_hex)
    bottom = hex_to_rgb(bottom_hex)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (w, y)], fill=color)


def rounded_box(
    draw: ImageDraw.ImageDraw, xyxy: tuple[float, float, float, float], radius: float, fill, outline=None
) -> None:
    draw.rounded_rectangle(xyxy, radius=radius, fill=fill, outline=outline, width=3)


def arrow(draw: ImageDraw.ImageDraw, start: tuple[float, float], end: tuple[float, float], color, width: int) -> None:
    draw.line([start, end], fill=color, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    head_len = width * 3
    for da in (0.5, -0.5):
        ax = end[0] - head_len * math.cos(angle - da)
        ay = end[1] - head_len * math.sin(angle - da)
        draw.line([end, (ax, ay)], fill=color, width=width)


def _new_canvas(fmt: FormatSpec, theme: SlideTheme) -> Image.Image:
    img = Image.new("RGB", (fmt.width, fmt.height), hex_to_rgb(theme.background))
    lighter = _lighten(theme.background, 0.15)
    draw_gradient(img, theme.background, lighter)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, round(fmt.width * 0.01) or 6, fmt.height], fill=hex_to_rgb(theme.accent))
    if theme.logo and theme.logo.exists():
        _paste_logo(img, theme, fmt)
    return img


def _paste_logo(img: Image.Image, theme: SlideTheme, fmt: FormatSpec) -> None:
    assert theme.logo is not None
    logo = Image.open(theme.logo).convert("RGBA")
    target_w = round(fmt.width * 0.06)
    scale = target_w / logo.width
    logo = logo.resize((target_w, max(1, round(logo.height * scale))))
    alpha = logo.split()[3].point(lambda p: int(p * 0.85))
    logo.putalpha(alpha)
    x = fmt.width - target_w - round(fmt.width * 0.03)
    img.paste(logo, (x, round(fmt.height * 0.03)), logo)


def _lighten(hex_color: str, amount: float) -> str:
    r, g, b = hex_to_rgb(hex_color)
    r = min(255, int(r + (255 - r) * amount))
    g = min(255, int(g + (255 - g) * amount))
    b = min(255, int(b + (255 - b) * amount))
    return f"#{r:02x}{g:02x}{b:02x}"


def render_slide(
    scene: Scene, video_format: VideoFormat, fmt: FormatSpec, theme: SlideTheme, out_path: Path, language: str = "en"
) -> Path:
    """Render one slide PNG at the format resolution (LLR-SLD-01, LLR-SLD-02)."""
    img = _new_canvas(fmt, theme)
    draw = ImageDraw.Draw(img)
    is_short = video_format == VideoFormat.SHORT

    if scene.visual == VisualType.TITLE:
        _draw_title(draw, img, scene, fmt, theme, language, is_short)
    elif scene.visual == VisualType.BULLETS:
        _draw_bullets(draw, img, scene, fmt, theme, language, is_short)
    elif scene.visual == VisualType.DEFINITION:
        _draw_definition(draw, img, scene, fmt, theme, language, is_short)
    elif scene.visual == VisualType.COMPARISON:
        _draw_comparison(draw, img, scene, fmt, theme, language, is_short)
    elif scene.visual == VisualType.FLOW:
        _draw_flow(draw, img, scene, fmt, theme, is_short)
    elif scene.visual == VisualType.CODE:
        _draw_code(draw, img, scene, fmt, theme, is_short)
    else:
        _draw_title(draw, img, scene, fmt, theme, language, is_short)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
    return out_path


def _draw_title(draw, img, scene, fmt, theme, language, is_short) -> None:
    max_w = fmt.width * 0.8
    start_size = 96 if is_short else 110
    font, lines = fit_text(draw, scene.on_screen_title, _body_font_bold(theme), max_w, fmt.height * 0.3, start_size, 56)
    center_y = fmt.height * (0.4 if is_short else 0.5)
    _draw_centered_lines(draw, lines, font, fmt, center_y, hex_to_rgb(theme.text))
    underline_y = center_y + len(lines) * font.size * 0.8
    ux = fmt.width * 0.3
    draw.line([(ux, underline_y), (fmt.width - ux, underline_y)], fill=hex_to_rgb(theme.accent), width=6)


def _body_font_bold(theme: SlideTheme) -> Path:
    return theme.font_bold


def _draw_centered_lines(draw, lines, font, fmt, start_y, fill) -> None:
    y = start_y
    for line in lines:
        w = draw.textlength(line, font=font)
        draw.text((fmt.width / 2 - w / 2, y), line, font=font, fill=fill)
        y += font.size * 1.25


def _draw_bullets(draw, img, scene, fmt, theme, language, is_short) -> None:
    margin = fmt.width * 0.06
    title_font = _font(theme.font_bold, 60 if is_short else 72)
    draw.text(
        (margin, fmt.height * (0.16 if is_short else 0.10)),
        scene.on_screen_title,
        font=title_font,
        fill=hex_to_rgb(theme.text),
    )

    body_font_path = _body_font(theme, language)
    y = fmt.height * 0.30
    max_w = fmt.width * 0.82
    size = 40 if is_short else 52
    for bullet in scene.bullets or []:
        font, lines = fit_text(draw, bullet, body_font_path, max_w - 60, fmt.height * 0.12, size, 28)
        draw.ellipse([margin, y + 10, margin + 16, y + 26], fill=hex_to_rgb(theme.accent))
        for i, line in enumerate(lines):
            draw.text((margin + 40, y + i * font.size * 1.3), line, font=font, fill=hex_to_rgb(theme.text))
        y += max(1, len(lines)) * font.size * 1.6 + 20


def _draw_definition(draw, img, scene, fmt, theme, language, is_short) -> None:
    term = scene.term or ""
    definition = scene.definition or ""
    term_font, term_lines = fit_text(draw, term, theme.font_bold, fmt.width * 0.8, fmt.height * 0.15, 100, 56)
    term_y = fmt.height * (0.35 if is_short else 0.38)
    _draw_centered_lines(draw, term_lines, term_font, fmt, term_y, hex_to_rgb(theme.accent))

    def_font, def_lines = fit_text(
        draw, definition, _body_font(theme, language), fmt.width * 0.7, fmt.height * 0.2, 48, 26
    )
    def_y = fmt.height * (0.5 if is_short else 0.6)
    _draw_centered_lines(draw, def_lines, def_font, fmt, def_y, hex_to_rgb(theme.text))


def _draw_comparison(draw, img, scene, fmt, theme, language, is_short) -> None:
    comp = scene.comparison
    if comp is None:
        return
    body_font_path = _body_font(theme, language)
    header_font = _font(theme.font_bold, 44 if is_short else 60)
    row_font = _font(body_font_path, 32 if is_short else 44)

    if is_short:
        card_w = fmt.width * 0.86
        card_h = fmt.height * 0.28
        positions = [
            (fmt.width * 0.07, fmt.height * 0.28),
            (fmt.width * 0.07, fmt.height * 0.60),
        ]
    else:
        card_w = fmt.width * 0.42
        card_h = fmt.height * 0.7
        positions = [
            (fmt.width * 0.04, fmt.height * 0.2),
            (fmt.width * 0.54, fmt.height * 0.2),
        ]

    for col, (x, y) in enumerate(positions):
        rounded_box(draw, (x, y, x + card_w, y + card_h), 24, fill=hex_to_rgb(_lighten(theme.background, 0.08)))
        draw.rectangle([x, y, x + card_w, y + card_h * 0.15], fill=hex_to_rgb(theme.primary))
        header = comp.headers[col]
        hw = draw.textlength(header, font=header_font)
        draw.text((x + card_w / 2 - hw / 2, y + card_h * 0.04), header, font=header_font, fill=hex_to_rgb(theme.text))
        row_y = y + card_h * 0.22
        row_h = (card_h * 0.75) / max(len(comp.rows), 1)
        for row in comp.rows:
            cell = row[col]
            font, lines = fit_text(draw, cell, body_font_path, card_w * 0.85, row_h, int(row_font.size), 20)
            draw.text((x + card_w * 0.08, row_y), lines[0], font=font, fill=hex_to_rgb(theme.text))
            divider_color = hex_to_rgb(_lighten(theme.background, 0.2))
            draw.line(
                [(x + 10, row_y + row_h - 4), (x + card_w - 10, row_y + row_h - 4)], fill=divider_color, width=2
            )
            row_y += row_h


def _draw_flow(draw, img, scene, fmt, theme, is_short) -> None:
    steps = scene.flow_steps or []
    n = len(steps)
    if n == 0:
        return
    box_font = _font(theme.font_bold, 36 if is_short else 44)

    def _box(x: float, y: float, w: float, h: float, step: str) -> None:
        rounded_box(draw, (x, y, x + w, y + h), 20, fill=hex_to_rgb(theme.primary))
        tw = draw.textlength(step, font=box_font)
        draw.text((x + w / 2 - tw / 2, y + h / 2 - box_font.size / 2), step, font=box_font, fill=hex_to_rgb(theme.text))

    if is_short:
        box_w = fmt.width * 0.7
        box_h = fmt.height * 0.09
        gap = (fmt.height * 0.8 - box_h * n) / max(n - 1, 1) if n > 1 else 0
        x = (fmt.width - box_w) / 2
        y = fmt.height * 0.12
        for i, step in enumerate(steps):
            _box(x, y, box_w, box_h, step)
            if i < n - 1:
                accent = hex_to_rgb(theme.accent)
                arrow(draw, (fmt.width / 2, y + box_h + 4), (fmt.width / 2, y + box_h + gap - 4), accent, 8)
            y += box_h + gap
    else:
        box_w = (fmt.width * 0.88) / n * 0.75
        box_h = fmt.height * 0.22
        total_span = fmt.width * 0.88
        gap = (total_span - box_w * n) / max(n - 1, 1) if n > 1 else 0
        x = fmt.width * 0.06
        y = fmt.height / 2 - box_h / 2
        for i, step in enumerate(steps):
            _box(x, y, box_w, box_h, step)
            if i < n - 1:
                accent = hex_to_rgb(theme.accent)
                arrow(draw, (x + box_w + 4, y + box_h / 2), (x + box_w + gap - 4, y + box_h / 2), accent, 8)
            x += box_w + gap


_KEYWORDS = {"def", "return", "import", "from", "class", "for", "in", "if"}


def _draw_code(draw, img, scene, fmt, theme, is_short) -> None:
    code = scene.code or ""
    lines = code.splitlines()[:12] if not is_short else code.splitlines()[:10]
    panel_w = fmt.width * 0.88
    panel_h = fmt.height * (0.5 if is_short else 0.6)
    x = (fmt.width - panel_w) / 2
    y = (fmt.height - panel_h) / 2
    rounded_box(draw, (x, y, x + panel_w, y + panel_h), 16, fill=(17, 24, 39))

    for i, dot_color in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        draw.ellipse([x + 20 + i * 24, y + 16, x + 34 + i * 24, y + 30], fill=dot_color)

    size = 34 if is_short else 40
    font = _font(theme.font_mono, size)
    line_h = size * 1.35
    ty = y + 50
    for line in lines:
        cx = x + 24
        for token in _tokenize(line):
            color = (198, 146, 233) if token.strip() in _KEYWORDS else (226, 232, 240)
            draw.text((cx, ty), token, font=font, fill=color)
            cx += draw.textlength(token, font=font)
        ty += line_h


def _tokenize(line: str) -> list[str]:
    return re.findall(r"\S+\s*|\s+", line) or [line]


def render_title_bar(topic_title: str, fmt: FormatSpec, theme: SlideTheme) -> Image.Image:
    """RGBA overlay for the Short top title bar, transparent below the bar (LLR-CMP-05)."""
    img = Image.new("RGBA", (fmt.width, fmt.height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    bar_h = round(fmt.height * 0.12)
    draw.rectangle([0, 0, fmt.width, bar_h], fill=hex_to_rgb(theme.primary, 235))

    words = topic_title.split()[:5]
    text = " ".join(words)
    font, lines = fit_text(draw, text, theme.font_bold, fmt.width * 0.9, bar_h * 0.8, 56, 28)
    line = lines[0]
    w = draw.textlength(line, font=font)
    draw.text((fmt.width / 2 - w / 2, bar_h / 2 - font.size / 2), line, font=font, fill=hex_to_rgb(theme.text))
    return img
