from __future__ import annotations

import pytest
from pydantic import ValidationError

from edutube.models import (
    Comparison,
    Scene,
    SceneRole,
    Script,
    VideoFormat,
    VisualType,
)


def test_script_short_word_count(script_short):
    assert 75 <= script_short.word_count <= 100


def test_script_long_word_count(script_long):
    assert 600 <= script_long.word_count <= 750


def test_short_script_rejects_disallowed_visual_type():
    scenes = [
        Scene(index=0, role=SceneRole.HOOK, visual=VisualType.TITLE, narration="hook here", on_screen_title="Hook"),
        Scene(
            index=1,
            role=SceneRole.CONTENT,
            visual=VisualType.CODE,
            narration="content",
            on_screen_title="Code",
            code="print(1)",
        ),
        Scene(index=2, role=SceneRole.CTA, visual=VisualType.TITLE, narration="cta", on_screen_title="CTA"),
    ]
    with pytest.raises(ValidationError, match="only allow title/bullets/definition/broll"):
        Script(topic_title="t", format=VideoFormat.SHORT, language="en", title="T", hook="H", scenes=scenes)


def test_long_script_requires_core_roles():
    scenes = [
        Scene(index=i, role=SceneRole.CONTENT, visual=VisualType.TITLE, narration="x " * 10, on_screen_title="X")
        for i in range(7)
    ]
    with pytest.raises(ValidationError, match="must include roles"):
        Script(topic_title="t", format=VideoFormat.LONG, language="en", title="T", hook="H", scenes=scenes)


def test_bullets_scene_requires_2_to_4_bullets():
    with pytest.raises(ValidationError, match="2-4 bullets"):
        Scene(
            index=0,
            role=SceneRole.CONTENT,
            visual=VisualType.BULLETS,
            narration="x",
            on_screen_title="X",
            bullets=["only one"],
        )


def test_comparison_scene_needs_comparison_block():
    with pytest.raises(ValidationError, match="comparison block"):
        Scene(index=0, role=SceneRole.CONTENT, visual=VisualType.COMPARISON, narration="x", on_screen_title="X")


def test_comparison_scene_valid():
    scene = Scene(
        index=0,
        role=SceneRole.CONTENT,
        visual=VisualType.COMPARISON,
        narration="x",
        on_screen_title="X",
        comparison=Comparison(headers=("A", "B"), rows=[("1", "2"), ("3", "4")]),
    )
    assert scene.comparison.headers == ("A", "B")


def test_code_scene_line_length_limit():
    with pytest.raises(ValidationError, match="60 chars"):
        Scene(
            index=0,
            role=SceneRole.CONTENT,
            visual=VisualType.CODE,
            narration="x",
            on_screen_title="X",
            code="a" * 61,
        )
