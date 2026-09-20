"""Time formatting and timezone helpers (LLD src layout, LLR-QTA-02, LLR-SUB-05)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


def pacific_day_key(now: datetime | None = None) -> str:
    """Current date in America/Los_Angeles, YYYY-MM-DD (LLR-QTA-02)."""
    moment = now.astimezone(PACIFIC) if now else datetime.now(PACIFIC)
    return moment.date().isoformat()


def fmt_srt_time(seconds: float) -> str:
    """HH:MM:SS,mmm (LLR-SUB-05)."""
    if seconds < 0:
        seconds = 0
    total_ms = round(seconds * 1000)
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def fmt_ass_time(seconds: float) -> str:
    """H:MM:SS.cc (centiseconds) for ASS subtitle events."""
    if seconds < 0:
        seconds = 0
    total_cs = round(seconds * 100)
    hours, rem = divmod(total_cs, 360_000)
    minutes, rem = divmod(rem, 6_000)
    secs, cs = divmod(rem, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{cs:02d}"


def fmt_chapter_time(seconds: float) -> str:
    """MM:SS, or H:MM:SS if >= 1 hour (LLD §8.8)."""
    total_s = round(seconds)
    hours, rem = divmod(total_s, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
