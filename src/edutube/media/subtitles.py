"""Subtitle generation: burned-in ASS + SRT sidecar (LLD §8.5, LLR-SUB-01..05)."""

from __future__ import annotations

from dataclasses import dataclass, field

from edutube.config import BrandCfg, FormatSpec
from edutube.models import VoiceResult, Word
from edutube.utils.timeutil import fmt_ass_time, fmt_srt_time

SHORT_MAX_WORDS = 4
SHORT_MAX_CHARS = 18
SHORT_MIN_DURATION = 0.3

LONG_MAX_CHARS = 42
LONG_MAX_LINES = 2
LONG_MAX_DURATION = 7.0

_PUNCT_END = (".", ",", "!", "?", ";", ":")


@dataclass
class Cue:
    start: float
    end: float
    words: list[Word] = field(default_factory=list)
    text: str = ""


def build_timeline(voice: VoiceResult, scene_starts: list[float]) -> list[Word]:
    """Offset each scene's words by its scene start time (LLR-SUB-01)."""
    timeline: list[Word] = []
    for scene in voice.scenes:
        offset = scene_starts[scene.index] if scene.index < len(scene_starts) else 0.0
        for w in scene.words:
            timeline.append(Word(word=w.word, start=w.start + offset, end=w.end + offset))
    return timeline


def _ends_with_punct(word: str) -> bool:
    return bool(word) and word.rstrip()[-1:] in _PUNCT_END


def chunk_short(
    words: list[Word], max_words: int = SHORT_MAX_WORDS, max_chars: int = SHORT_MAX_CHARS
) -> list[Cue]:
    """Group 1-4 words per chunk, breaking on punctuation, max 18 chars (LLR-SUB-02)."""
    cues: list[Cue] = []
    current: list[Word] = []
    current_chars = 0
    for w in words:
        added = len(w.word) + (1 if current else 0)
        if current and (len(current) >= max_words or current_chars + added > max_chars):
            cues.append(_short_cue(current))
            current, current_chars = [], 0
            added = len(w.word)
        current.append(w)
        current_chars += added
        if _ends_with_punct(w.word) or len(current) >= max_words:
            cues.append(_short_cue(current))
            current, current_chars = [], 0
    if current:
        cues.append(_short_cue(current))
    return cues


def _short_cue(words: list[Word]) -> Cue:
    start = words[0].start
    end = max(words[-1].end, start + SHORT_MIN_DURATION)
    return Cue(start=start, end=end, words=list(words))


def _wrap_lines(text: str, max_chars: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def chunk_long(
    words: list[Word],
    max_chars: int = LONG_MAX_CHARS,
    max_lines: int = LONG_MAX_LINES,
    max_dur: float = LONG_MAX_DURATION,
) -> list[Cue]:
    """Lines <=42 chars, <=2 lines, <=7s per cue, break on punctuation first (LLR-SUB-04)."""
    cues: list[Cue] = []
    current: list[Word] = []
    for w in words:
        trial = [*current, w]
        lines = _wrap_lines(" ".join(x.word for x in trial), max_chars)
        duration = trial[-1].end - trial[0].start
        if current and (len(lines) > max_lines or duration > max_dur):
            cues.append(_long_cue(current, max_chars))
            current = [w]
        else:
            current = trial
        if _ends_with_punct(w.word):
            cues.append(_long_cue(current, max_chars))
            current = []
    if current:
        cues.append(_long_cue(current, max_chars))
    return cues


def _long_cue(words: list[Word], max_chars: int) -> Cue:
    start = words[0].start
    end = words[-1].end
    text = "\n".join(_wrap_lines(" ".join(w.word for w in words), max_chars))
    return Cue(start=start, end=end, words=list(words), text=text)


def _bgr_hex(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"{b}{g}{r}".upper()


def ass_style_color(hex_color: str, alpha_hex: str = "00") -> str:
    return f"&H{alpha_hex}{_bgr_hex(hex_color)}&"


def ass_override_color(hex_color: str) -> str:
    return f"&H{_bgr_hex(hex_color)}&"


def to_ass_short(cues: list[Cue], fmt: FormatSpec, brand: BrandCfg) -> str:
    """Karaoke-style active-word highlight for Shorts (LLR-SUB-03)."""
    size = round(80 * fmt.width / 1080)
    x = fmt.width // 2
    y = round(fmt.height * 0.6)
    margin = round(fmt.width * 0.08)
    primary = ass_style_color(brand.text)
    outline = ass_style_color("#000000")
    back = "&H64000000"
    accent = ass_override_color(brand.accent)
    white = ass_override_color(brand.text)

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {fmt.width}",
        f"PlayResY: {fmt.height}",
        "WrapStyle: 2",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,Poppins,{size},{primary},{primary},{outline},{back},-1,0,0,0,100,100,0,0,"
        f"1,6,2,5,{margin},{margin},160,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    for cue in cues:
        upper_words = [w.word.upper() for w in cue.words]
        for i, w in enumerate(cue.words):
            start = w.start
            end = cue.words[i + 1].start if i + 1 < len(cue.words) else cue.end
            if end <= start:
                end = start + 0.05
            parts = [
                f"{{\\c{accent}}}{token}{{\\c{white}}}" if j == i else token
                for j, token in enumerate(upper_words)
            ]
            text = " ".join(parts)
            lines.append(
                f"Dialogue: 0,{fmt_ass_time(start)},{fmt_ass_time(end)},Cap,,0,0,0,,"
                f"{{\\pos({x},{y})}}{text}"
            )
    return "\n".join(lines) + "\n"


def to_ass_long(cues: list[Cue], fmt: FormatSpec, brand: BrandCfg) -> str:
    """Bottom-center captions for Long videos (LLR-SUB-04)."""
    size = round(48 * fmt.width / 1920)
    margin_v = round(60 * fmt.height / 1080)
    margin = round(fmt.width * 0.06)
    primary = ass_style_color(brand.text)
    outline = ass_style_color("#000000")
    back = "&H64000000"

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {fmt.width}",
        f"PlayResY: {fmt.height}",
        "WrapStyle: 2",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,Poppins,{size},{primary},{primary},{outline},{back},-1,0,0,0,100,100,0,0,"
        f"3,0,0,2,{margin},{margin},{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for cue in cues:
        ass_text = cue.text.replace("\n", "\\N")
        lines.append(f"Dialogue: 0,{fmt_ass_time(cue.start)},{fmt_ass_time(cue.end)},Cap,,0,0,0,,{ass_text}")
    return "\n".join(lines) + "\n"


def ensure_non_overlapping(cues: list[Cue]) -> list[Cue]:
    """SRT cues must not overlap and are strictly increasing (LLR-SUB-05)."""
    fixed: list[Cue] = []
    prev_end = 0.0
    for cue in cues:
        start = max(cue.start, prev_end)
        end = max(cue.end, start + 0.05)
        fixed.append(Cue(start=start, end=end, words=cue.words, text=cue.text))
        prev_end = end
    return fixed


def to_srt(cues: list[Cue]) -> str:
    cues = ensure_non_overlapping(cues)
    lines: list[str] = []
    for i, cue in enumerate(cues, start=1):
        text = cue.text or " ".join(w.word for w in cue.words)
        lines.append(str(i))
        lines.append(f"{fmt_srt_time(cue.start)} --> {fmt_srt_time(cue.end)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)
