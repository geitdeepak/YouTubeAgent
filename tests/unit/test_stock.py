from __future__ import annotations

from pathlib import Path

import httpx
import respx

from edutube.db import Repository
from edutube.media.stock import PexelsProvider, load_assets, save_assets
from edutube.models import StockAttribution

SEARCH_URL = "https://api.pexels.com/videos/search"


def _video(vid: int, duration: int = 20, height: int = 1920) -> dict:
    return {
        "id": vid,
        "duration": duration,
        "url": f"https://pexels.com/video/{vid}",
        "user": {"name": "Jane Doe", "url": "https://pexels.com/@jane"},
        "video_files": [
            {"file_type": "video/mp4", "height": height, "link": f"https://cdn.pexels.com/{vid}_{height}.mp4"},
            {"file_type": "video/mp4", "height": 360, "link": f"https://cdn.pexels.com/{vid}_360.mp4"},
        ],
    }


@respx.mock
def test_fetch_video_selects_closest_height_and_downloads(repo: Repository, tmp_path: Path):
    respx.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json={"videos": [_video(1, height=1920)]})
    )
    respx.get("https://cdn.pexels.com/1_1920.mp4").mock(return_value=httpx.Response(200, content=b"fake mp4 bytes"))

    provider = PexelsProvider("fake-key", repo, tmp_path / "cache")
    result = provider.fetch_video(
        "server room", orientation="landscape", min_duration=5.0, target_height=1920,
        exclude_ids=set(), dest_dir=tmp_path / "job" / "broll",
    )
    assert result is not None
    path, attribution = result
    assert path.exists()
    assert path.read_bytes() == b"fake mp4 bytes"
    assert attribution.pexels_id == 1
    assert attribution.user_name == "Jane Doe"


@respx.mock
def test_fetch_video_excludes_already_used_ids(repo: Repository, tmp_path: Path):
    respx.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json={"videos": [_video(1), _video(2)]})
    )
    respx.get("https://cdn.pexels.com/2_1920.mp4").mock(return_value=httpx.Response(200, content=b"video2"))

    provider = PexelsProvider("fake-key", repo, tmp_path / "cache")
    result = provider.fetch_video(
        "computer", orientation="landscape", min_duration=5.0, target_height=1920,
        exclude_ids={1}, dest_dir=tmp_path / "job" / "broll",
    )
    assert result is not None
    _, attribution = result
    assert attribution.pexels_id == 2


@respx.mock
def test_fetch_video_returns_none_on_empty_results(repo: Repository, tmp_path: Path):
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"videos": []}))
    provider = PexelsProvider("fake-key", repo, tmp_path / "cache")
    result = provider.fetch_video(
        "nonexistent query", orientation="portrait", min_duration=5.0, target_height=1920,
        exclude_ids=set(), dest_dir=tmp_path,
    )
    assert result is None


@respx.mock
def test_fetch_video_returns_none_on_http_error(repo: Repository, tmp_path: Path):
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(500))
    provider = PexelsProvider("fake-key", repo, tmp_path / "cache")
    result = provider.fetch_video(
        "computer", orientation="landscape", min_duration=5.0, target_height=1920,
        exclude_ids=set(), dest_dir=tmp_path,
    )
    assert result is None


@respx.mock
def test_fetch_video_excludes_too_short_videos(repo: Repository, tmp_path: Path):
    respx.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json={"videos": [_video(1, duration=1)]})
    )
    provider = PexelsProvider("fake-key", repo, tmp_path / "cache")
    result = provider.fetch_video(
        "computer", orientation="landscape", min_duration=10.0, target_height=1920,
        exclude_ids=set(), dest_dir=tmp_path,
    )
    assert result is None


@respx.mock
def test_fetch_video_caches_download(repo: Repository, tmp_path: Path):
    route = respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"videos": [_video(1)]}))
    dl_route = respx.get("https://cdn.pexels.com/1_1920.mp4").mock(
        return_value=httpx.Response(200, content=b"cached bytes")
    )

    provider = PexelsProvider("fake-key", repo, tmp_path / "cache")
    provider.fetch_video(
        "computer", orientation="landscape", min_duration=5.0, target_height=1920,
        exclude_ids=set(), dest_dir=tmp_path / "job1",
    )
    provider.fetch_video(
        "computer", orientation="landscape", min_duration=5.0, target_height=1920,
        exclude_ids=set(), dest_dir=tmp_path / "job2",
    )
    assert route.call_count == 2  # search happens each time
    assert dl_route.call_count == 1  # but the actual file download is cached


def test_save_and_load_assets(tmp_path: Path):
    attributions = [StockAttribution(pexels_id=1, user_name="Jane", user_url="https://x", video_url="https://y")]
    path = tmp_path / "assets.json"
    save_assets(attributions, path)
    loaded = load_assets(path)
    assert loaded == attributions


def test_load_assets_missing_file_returns_empty(tmp_path: Path):
    assert load_assets(tmp_path / "nope.json") == []
