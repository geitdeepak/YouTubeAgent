from __future__ import annotations

from edutube.config import AppConfig
from edutube.content.metadata import assemble_description, assemble_tags, build_chapters, finalize_title
from edutube.models import Script, StockAttribution, VideoFormat, VideoMetadata


def test_assemble_tags_dedupes_and_truncates():
    tags = ["AI", "ai", "Machine Learning", "a" * 40, "AI"]
    result = assemble_tags(tags)
    assert result[0] == "AI"
    assert len([t for t in result if t.lower() == "ai"]) == 1
    assert all(len(t) <= 30 for t in result)
    assert sum(len(t) for t in result) + max(len(result) - 1, 0) <= 450


def test_assemble_tags_respects_total_budget():
    tags = ["x" * 30] * 20
    result = assemble_tags(tags)
    total = sum(len(t) for t in result) + max(len(result) - 1, 0)
    assert total <= 450


def test_finalize_title_truncates_and_strips_banned_words(cfg: AppConfig):
    meta = VideoMetadata(
        title="This Shocking AI Trick Will Blow Your Mind " * 3,
        description_intro="x", key_points=[], tags=[], hashtags=[], thumbnail_text="x",
    )
    title = finalize_title(meta, cfg, VideoFormat.LONG)
    assert len(title) <= 70
    assert "shocking" not in title.lower()


def test_finalize_title_adds_shorts_suffix(cfg: AppConfig):
    meta = VideoMetadata(title="What is RAG", description_intro="x", key_points=[], tags=[], hashtags=[], thumbnail_text="x")
    title = finalize_title(meta, cfg, VideoFormat.SHORT)
    assert title.endswith("#Shorts")


def test_build_chapters_from_scene_starts(script_long: Script):
    scene_starts = [0.0, 30.0, 60.0, 90.0, 130.0, 170.0, 200.0, 230.0, 260.0]
    chapters = build_chapters(script_long, scene_starts)
    assert chapters[0][0] == "00:00"
    assert len(chapters) >= 3


def test_build_chapters_merges_short_gaps():
    from edutube.models import Scene, SceneRole, VisualType

    def scene(i, role, chapter=None):
        return Scene(
            index=i, role=role, visual=VisualType.TITLE, narration="x " * 5,
            on_screen_title=str(i), chapter_title=chapter,
        )

    scenes = [
        scene(0, SceneRole.HOOK, "A"),
        scene(1, SceneRole.INTRO, "B"),  # gap to A is 5s (<10s) -> merges into A
        scene(2, SceneRole.CONTENT),
        scene(3, SceneRole.CONTENT, "C"),
        scene(4, SceneRole.CONTENT),
        scene(5, SceneRole.RECAP, "D"),
        scene(6, SceneRole.CTA),
    ]
    script = Script(topic_title="t", format=VideoFormat.LONG, language="en", title="T", hook="H", scenes=scenes)
    scene_starts = [0.0, 5.0, 20.0, 40.0, 60.0, 80.0, 100.0]
    chapters = build_chapters(script, scene_starts)
    starts = [c[0] for c in chapters]
    assert starts[0] == "00:00"
    assert len(chapters) == 3  # A (absorbed B), C, D


def test_assemble_description_includes_credits_and_disclosure(cfg: AppConfig):
    meta = VideoMetadata(
        title="T", description_intro="Intro sentence.", key_points=["point one", "point two"],
        tags=[], hashtags=["#AI", "#ML"], thumbnail_text="x",
    )
    attributions = [StockAttribution(pexels_id=1, user_name="Jane Doe", user_url="https://pexels.com/u/jane", video_url="https://pexels.com/v/1")]
    desc = assemble_description(meta, cfg, VideoFormat.LONG, [], attributions)
    assert "Jane Doe" in desc
    assert cfg.content.ai_disclosure_text in desc
    assert "<" not in desc and ">" not in desc


def test_assemble_description_short_adds_shorts_hashtag(cfg: AppConfig):
    meta = VideoMetadata(title="T", description_intro="x", key_points=[], tags=[], hashtags=["#AI"], thumbnail_text="x")
    desc = assemble_description(meta, cfg, VideoFormat.SHORT, [], [])
    assert "#Shorts" in desc
