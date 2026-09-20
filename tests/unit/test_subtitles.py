from __future__ import annotations

from edutube.config import AppConfig
from edutube.media.subtitles import (
    build_timeline,
    chunk_long,
    chunk_short,
    ensure_non_overlapping,
    to_ass_long,
    to_ass_short,
    to_srt,
)
from edutube.models import SceneAudio, VoiceResult, Word


def _words() -> list[Word]:
    return [
        Word(word="Hello", start=0.0, end=0.4),
        Word(word="world.", start=0.4, end=0.9),
        Word(word="This", start=1.0, end=1.2),
        Word(word="is", start=1.2, end=1.3),
        Word(word="a", start=1.3, end=1.35),
        Word(word="test", start=1.35, end=1.7),
    ]


def test_build_timeline_offsets_by_scene_start():
    voice = VoiceResult(
        scenes=[
            SceneAudio(index=0, path="a.mp3", duration=1.0, words=[Word(word="Hi", start=0.0, end=0.5)]),
            SceneAudio(index=1, path="b.mp3", duration=1.0, words=[Word(word="there", start=0.0, end=0.5)]),
        ],
        rate="+0%",
        total_duration=2.0,
    )
    timeline = build_timeline(voice, scene_starts=[0.0, 1.25])
    assert timeline[0].start == 0.0
    assert timeline[1].start == 1.25


def test_chunk_short_breaks_on_punctuation_and_max_words():
    cues = chunk_short(_words())
    assert len(cues) == 2
    assert [w.word for w in cues[0].words] == ["Hello", "world."]
    assert [w.word for w in cues[1].words] == ["This", "is", "a", "test"]
    assert cues[0].end >= cues[0].start + 0.3


def test_chunk_short_min_duration():
    words = [Word(word="Hi.", start=0.0, end=0.05)]
    cues = chunk_short(words)
    assert cues[0].end - cues[0].start >= 0.3


def test_chunk_long_respects_char_and_line_limits():
    long_words = [Word(word=f"word{i}", start=i * 0.3, end=i * 0.3 + 0.25) for i in range(40)]
    cues = chunk_long(long_words, max_chars=42, max_lines=2, max_dur=7.0)
    for cue in cues:
        lines = cue.text.split("\n")
        assert len(lines) <= 2
        assert all(len(line) <= 42 for line in lines)
        assert cue.end - cue.start <= 7.0 + 1e-6


def test_srt_cues_strictly_increasing_and_non_overlapping():
    cues = chunk_short(_words())
    # force an artificial overlap to verify the fixer works
    cues[1].start = cues[0].end - 0.1
    fixed = ensure_non_overlapping(cues)
    for prev, nxt in zip(fixed, fixed[1:], strict=False):
        assert nxt.start >= prev.end


def test_to_srt_format():
    cues = chunk_short(_words())
    srt = to_srt(cues)
    assert srt.startswith("1\n")
    assert "-->" in srt


def test_to_ass_short_has_one_dialogue_per_word():
    cfg = AppConfig(root=".")
    cues = chunk_short(_words())
    ass = to_ass_short(cues, cfg.formats["short"], cfg.brand)
    assert ass.count("Dialogue:") == len(_words())
    assert "[V4+ Styles]" in ass
    assert "PlayResX: 1080" in ass


def test_to_ass_long_has_one_dialogue_per_cue():
    cfg = AppConfig(root=".")
    long_words = [Word(word=f"word{i}", start=i * 0.3, end=i * 0.3 + 0.25) for i in range(10)]
    cues = chunk_long(long_words)
    ass = to_ass_long(cues, cfg.formats["long"], cfg.brand)
    assert ass.count("Dialogue:") == len(cues)
    assert "PlayResX: 1920" in ass
