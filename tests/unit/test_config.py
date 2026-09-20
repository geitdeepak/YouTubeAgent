from __future__ import annotations

from pathlib import Path

import pytest

from edutube.config import AppConfig, load_config
from edutube.errors import ConfigError


def test_load_config_missing_file(tmp_path: Path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yaml")


def test_load_config_invalid_yaml(tmp_path: Path):
    bad = tmp_path / "config.yaml"
    bad.write_text("llm: [this is not, a mapping", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(bad)


def test_load_config_invalid_field(tmp_path: Path):
    bad = tmp_path / "config.yaml"
    bad.write_text("formats:\n  short:\n    width: 'not-a-number'\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="formats.short.width"):
        load_config(bad)


def test_load_config_defaults(tmp_path: Path):
    good = tmp_path / "config.yaml"
    good.write_text("project:\n  channel_name: Test Channel\n", encoding="utf-8")
    cfg = load_config(good)
    assert cfg.project.channel_name == "Test Channel"
    assert cfg.formats["short"].min_s == 30
    assert cfg.formats["long"].max_words == 750


def test_resolve_relative_path(tmp_path: Path):
    cfg = AppConfig(root=tmp_path)
    resolved = cfg.resolve("data/topics.csv")
    assert resolved == tmp_path / "data" / "topics.csv"


def test_resolve_absolute_path(tmp_path: Path):
    cfg = AppConfig(root=tmp_path)
    abs_path = tmp_path / "elsewhere"
    assert cfg.resolve(abs_path) == abs_path


def test_format_spec_target_s():
    cfg = AppConfig(root=Path("."))
    assert cfg.formats["short"].target_s == 35
    assert cfg.formats["long"].target_s == 270
