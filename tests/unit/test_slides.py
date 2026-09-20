from __future__ import annotations

from edutube.config import AppConfig
from edutube.media.slides import build_theme, render_slide, render_title_bar
from edutube.models import Script, VideoFormat


def test_render_every_template_short(cfg: AppConfig, script_short: Script, tmp_path):
    theme = build_theme(cfg)
    for scene in script_short.scenes:
        out = tmp_path / f"short_{scene.index}.png"
        path = render_slide(scene, VideoFormat.SHORT, cfg.formats["short"], theme, out, language="en")
        assert path.exists()
        from PIL import Image

        img = Image.open(path)
        assert img.size == (1080, 1920)


def test_render_every_template_long(cfg: AppConfig, script_long: Script, tmp_path):
    theme = build_theme(cfg)
    for scene in script_long.scenes:
        out = tmp_path / f"long_{scene.index}.png"
        path = render_slide(scene, VideoFormat.LONG, cfg.formats["long"], theme, out, language="en")
        assert path.exists()
        from PIL import Image

        img = Image.open(path)
        assert img.size == (1920, 1080)


def test_render_title_bar_overlay_short(cfg: AppConfig):
    theme = build_theme(cfg)
    overlay = render_title_bar("What is a Transformer?", cfg.formats["short"], theme)
    assert overlay.size == (1080, 1920)
    assert overlay.mode == "RGBA"
