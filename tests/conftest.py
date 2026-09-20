from __future__ import annotations

import json
from pathlib import Path

import pytest

from edutube.config import AppConfig
from edutube.db import Repository
from edutube.models import Script

FIXTURES_DIR = Path(__file__).parent / "fixtures"
PROJECT_ROOT = Path(__file__).parent.parent
REAL_FONTS_DIR = PROJECT_ROOT / "assets" / "fonts"


@pytest.fixture()
def tmp_root(tmp_path: Path) -> Path:
    (tmp_path / "data").mkdir()
    (tmp_path / "secrets").mkdir()
    (tmp_path / "workspace").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "assets" / "fonts").mkdir(parents=True)
    (tmp_path / "assets" / "music").mkdir(parents=True)
    return tmp_path


@pytest.fixture()
def cfg(tmp_root: Path) -> AppConfig:
    config = AppConfig(root=tmp_root)
    # Point at the project's real font files (LLR-SLD-05) instead of the empty tmp assets dir.
    config.brand.font_bold = str(REAL_FONTS_DIR / "Poppins-Bold.ttf")
    config.brand.font_regular = str(REAL_FONTS_DIR / "Poppins-Regular.ttf")
    config.brand.font_mono = str(REAL_FONTS_DIR / "JetBrainsMono-Regular.ttf")
    config.brand.font_hindi = str(REAL_FONTS_DIR / "NotoSansDevanagari-Regular.ttf")
    return config


@pytest.fixture()
def repo(tmp_root: Path) -> Repository:
    r = Repository(tmp_root / "data" / "edutube.db")
    yield r
    r.close()


@pytest.fixture()
def script_short() -> Script:
    data = json.loads((FIXTURES_DIR / "script_short.json").read_text(encoding="utf-8"))
    return Script.model_validate(data)


@pytest.fixture()
def script_long() -> Script:
    data = json.loads((FIXTURES_DIR / "script_long.json").read_text(encoding="utf-8"))
    return Script.model_validate(data)
