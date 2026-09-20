from __future__ import annotations

from datetime import UTC, datetime

from edutube.config import AppConfig
from edutube.content.script_writer import enforce_broll_ratio, enforce_word_range, save_script, write_script
from edutube.errors import ScriptLengthError
from edutube.llm.fake_provider import FakeLLMProvider
from edutube.models import Level, Script, Topic, VideoFormat, VisualType


def _topic() -> Topic:
    return Topic(title="What is a Neural Network?", level=Level.BEGINNER, created_at=datetime.now(UTC))


def test_write_script_short_uses_fake_llm(cfg: AppConfig, script_short: Script):
    fake = FakeLLMProvider()
    fake.register("script_short.md", lambda: script_short)
    result = write_script(fake, cfg, _topic(), VideoFormat.SHORT)
    assert result.format == VideoFormat.SHORT
    assert 75 <= result.word_count <= 100


def test_enforce_word_range_triggers_adjust_length(cfg: AppConfig, script_short: Script):
    fake = FakeLLMProvider()
    # make the narration way too short so word range enforcement kicks in
    trimmed = script_short.model_copy(deep=True)
    for s in trimmed.scenes:
        s.narration = "short"
    fake.register("adjust_length.md", lambda: script_short)
    spec = cfg.formats["short"]
    result = enforce_word_range(fake, cfg, trimmed, spec)
    assert spec.min_words <= result.word_count <= spec.max_words
    assert fake.calls[0]["prompt_name"] == "adjust_length.md"


def test_enforce_word_range_raises_if_still_out_of_tolerance(cfg: AppConfig, script_short: Script):
    fake = FakeLLMProvider()
    too_short = script_short.model_copy(deep=True)
    for s in too_short.scenes:
        s.narration = "hi"
    fake.register("adjust_length.md", lambda: too_short)  # still too short after "fix"
    spec = cfg.formats["short"]
    try:
        enforce_word_range(fake, cfg, too_short, spec)
        raise AssertionError("expected ScriptLengthError")
    except ScriptLengthError:
        pass


def test_enforce_broll_ratio_converts_excess_broll(script_long: Script):
    over_broll = script_long.model_copy(deep=True)
    for s in over_broll.scenes:
        if s.role.value == "content":
            s.visual = VisualType.BROLL
            s.broll_query = "technology"
    fixed = enforce_broll_ratio(over_broll)
    non_broll = sum(1 for s in fixed.scenes if s.visual != VisualType.BROLL)
    assert non_broll / len(fixed.scenes) >= 0.6


def test_enforce_broll_ratio_noop_for_short(script_short: Script):
    result = enforce_broll_ratio(script_short)
    assert result == script_short


def test_save_and_load_script_roundtrip(tmp_path, script_short: Script):
    from edutube.content.script_writer import load_script

    path = tmp_path / "script.json"
    save_script(script_short, path)
    loaded = load_script(path)
    assert loaded.title == script_short.title
    assert loaded.word_count == script_short.word_count
