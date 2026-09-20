from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from edutube.utils.timeutil import fmt_ass_time, fmt_chapter_time, fmt_srt_time, pacific_day_key


def test_fmt_srt_time():
    assert fmt_srt_time(0) == "00:00:00,000"
    assert fmt_srt_time(61.5) == "00:01:01,500"
    assert fmt_srt_time(3661.234) == "01:01:01,234"


def test_fmt_ass_time():
    assert fmt_ass_time(0) == "0:00:00.00"
    assert fmt_ass_time(61.5) == "0:01:01.50"


def test_fmt_chapter_time():
    assert fmt_chapter_time(0) == "00:00"
    assert fmt_chapter_time(72) == "01:12"
    assert fmt_chapter_time(3661) == "1:01:01"


def test_pacific_day_key_is_stable_for_known_datetime():
    dt = datetime(2026, 1, 1, 10, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    assert pacific_day_key(dt) == "2026-01-01"
