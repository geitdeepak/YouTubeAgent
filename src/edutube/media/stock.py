"""Pexels stock b-roll provider (LLD §8.4, LLR-STK-01..06)."""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from pathlib import Path

import httpx

from edutube.db import Repository
from edutube.logging_setup import get_logger
from edutube.models import StockAttribution

log = get_logger("media.stock")

CONTEXT_WORDS = ["technology", "computer", "data"]


class StockProvider(ABC):
    @abstractmethod
    def fetch_video(
        self,
        query: str,
        *,
        orientation: str,
        min_duration: float,
        target_height: int,
        exclude_ids: set[int],
        dest_dir: Path,
    ) -> tuple[Path, StockAttribution] | None: ...


class PexelsProvider(StockProvider):
    BASE = "https://api.pexels.com/videos/search"

    def __init__(self, api_key: str, repo: Repository, cache_dir: Path) -> None:
        self.api_key = api_key
        self.repo = repo
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._enriched_once: set[str] = set()

    def _enrich_query(self, query: str) -> str:
        words = query.split()
        if len(words) == 1:
            return f"{query} {CONTEXT_WORDS[0]}"
        return query

    def fetch_video(
        self,
        query: str,
        *,
        orientation: str,
        min_duration: float,
        target_height: int,
        exclude_ids: set[int],
        dest_dir: Path,
    ) -> tuple[Path, StockAttribution] | None:
        try:
            videos = self._search(query, orientation)
        except Exception as e:  # noqa: BLE001 -- LLR-STK-04: any error -> fallback
            log.warning("Pexels search failed for %r: %s", query, e)
            return None
        if not videos:
            log.warning("Pexels returned no results for %r", query)
            return None

        for v in videos:
            vid = v.get("id")
            if not isinstance(vid, int) or vid in exclude_ids:
                continue
            duration = v.get("duration", 0)
            if duration < min_duration / 2:
                continue
            file = self._pick_file(v.get("video_files", []), target_height)
            if file is None:
                continue
            try:
                path = self._download(vid, file, dest_dir)
            except Exception as e:  # noqa: BLE001
                log.warning("Pexels download failed for id=%s: %s", vid, e)
                continue
            attribution = StockAttribution(
                pexels_id=vid,
                user_name=v.get("user", {}).get("name", "unknown"),
                user_url=v.get("user", {}).get("url", ""),
                video_url=v.get("url", ""),
            )
            return path, attribution
        return None

    def _pick_file(self, files: list[dict], target_height: int, min_height: int = 720) -> dict | None:
        candidates = [
            f for f in files if f.get("file_type") == "video/mp4" and (f.get("height") or 0) >= min_height
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda f: abs((f.get("height") or 0) - target_height))

    def _search(self, query: str, orientation: str) -> list[dict]:
        enriched = self._enrich_query(query)
        with httpx.Client(timeout=30, headers={"Authorization": self.api_key}) as client:
            resp = client.get(
                self.BASE,
                params={"query": enriched, "orientation": orientation, "size": "medium", "per_page": 10},
            )
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            log.warning("Pexels rate limited; waiting %ds then giving up on retry", retry_after)
            time.sleep(min(retry_after, 60))
            return []
        resp.raise_for_status()
        return resp.json().get("videos", [])

    def _download(self, video_id: int, file: dict, dest_dir: Path) -> Path:
        height = file.get("height")
        cache_key = f"pexels:{video_id}:{height}"
        cached = self.repo.cache_get(cache_key)
        cache_path = self.cache_dir / f"{video_id}_{height}.mp4"

        if cached is None or not Path(cached["path"]).exists():
            with httpx.Client(timeout=60) as client:
                with client.stream("GET", file["link"]) as resp:
                    resp.raise_for_status()
                    with open(cache_path, "wb") as f:
                        for chunk in resp.iter_bytes():
                            f.write(chunk)
            self.repo.cache_put(cache_key, str(cache_path), {"video_id": video_id, "height": height})

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / f"scene_src_{video_id}.mp4"
        dest_path.write_bytes(cache_path.read_bytes())
        return dest_path


def save_assets(attributions: list[StockAttribution], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([a.model_dump() for a in attributions], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_assets(path: Path) -> list[StockAttribution]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [StockAttribution(**a) for a in data]
