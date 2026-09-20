"""Resumable YouTube upload (LLD §8.9, LLR-UPL-01..08)."""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from edutube.config import AppConfig, PublishCfg
from edutube.db import Repository
from edutube.errors import QuotaExhaustedError, UploadError
from edutube.logging_setup import get_logger
from edutube.models import Job, VideoFormat, VideoMetadata
from edutube.publish.quota import QuotaTracker, upload_cost
from edutube.publish.youtube_auth import get_credentials, youtube_client

log = get_logger("publish.uploader")

MAX_RETRIES = 5
RETRYABLE_STATUS = (500, 502, 503, 504)


def _next_publish_at(hhmm: str, tz_name: str) -> str:
    tz = ZoneInfo(tz_name)
    now_local = datetime.now(tz)
    hour, minute = (int(x) for x in hhmm.split(":"))
    candidate = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now_local:
        candidate += timedelta(days=1)
    return candidate.astimezone(UTC).isoformat().replace("+00:00", "Z")


def build_request_body(meta: VideoMetadata, cfg: PublishCfg, timezone: str) -> dict:
    """LLR-UPL-02: the videos.insert request body."""
    body: dict = {
        "snippet": {
            "title": meta.title,
            "description": meta.description,
            "tags": meta.tags,
            "categoryId": cfg.category_id,
            "defaultLanguage": cfg.default_language,
            "defaultAudioLanguage": cfg.default_language,
        },
        "status": {
            "privacyStatus": cfg.privacy_status,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": cfg.contains_synthetic_media,
        },
    }
    if cfg.schedule_publish_time and cfg.privacy_status == "private":
        body["status"]["publishAt"] = _next_publish_at(cfg.schedule_publish_time, timezone)
    return body


@dataclass
class UploadResult:
    video_id: str
    url: str
    already_uploaded: bool = False
    dry_run: bool = False
    thumbnail_set: bool = False
    captions_set: bool = False


class Uploader:
    def __init__(self, repo: Repository, quota: QuotaTracker, cfg: AppConfig, token_path: Path) -> None:
        self.repo = repo
        self.quota = quota
        self.cfg = cfg
        self.token_path = token_path

    def upload(
        self,
        job: Job,
        meta: VideoMetadata,
        final_mp4: Path,
        *,
        thumbnail: Path | None = None,
        srt: Path | None = None,
        dry_run: bool = False,
    ) -> UploadResult:
        existing = self.repo.get_upload(job.id)
        if existing:
            log.info("Job %s already uploaded: %s", job.id, existing["url"])
            return UploadResult(video_id=existing["video_id"], url=existing["url"], already_uploaded=True)

        body = build_request_body(meta, self.cfg.publish, self.cfg.project.timezone)

        if dry_run:
            print(json.dumps(body, indent=2))  # noqa: T201 -- LLR-UPL-07
            size = final_mp4.stat().st_size if final_mp4.exists() else 0
            print(f"video file: {final_mp4} ({size} bytes)")  # noqa: T201
            return UploadResult(video_id="", url="", dry_run=True)

        cost = upload_cost(job, self.cfg.quota, upload_captions=self.cfg.publish.upload_captions)
        if not self.quota.can_spend(cost):
            raise QuotaExhaustedError(f"Uploading would exceed today's quota budget ({cost} units needed)")

        creds = get_credentials(self.token_path)
        yt = youtube_client(creds)

        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload

        media = MediaFileUpload(str(final_mp4), chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4")
        request = yt.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        retry = 0
        while response is None:
            try:
                _status, response = request.next_chunk()
            except HttpError as e:
                status_code = getattr(e.resp, "status", None)
                if status_code in RETRYABLE_STATUS:
                    retry += 1
                elif status_code == 403 and "quotaExceeded" in str(e):
                    self.quota.mark_exhausted()
                    raise QuotaExhaustedError("YouTube quota exceeded") from e
                else:
                    raise UploadError(str(e)) from e
            except (ConnectionError, TimeoutError):
                retry += 1
            if retry > MAX_RETRIES:
                raise UploadError("max retries exceeded during upload")
            if retry:
                time.sleep(random.random() * 2**retry)

        video_id = response["id"]
        self.quota.record(self.cfg.quota.costs.videos_insert, "videos.insert", job.id)
        url = f"https://youtu.be/{video_id}"
        self.repo.record_upload(job.id, video_id, url, self.cfg.publish.privacy_status)

        thumbnail_set = False
        if thumbnail is not None and job.format == VideoFormat.LONG:
            thumbnail_set = self._set_thumbnail(yt, video_id, thumbnail, job.id)

        captions_set = False
        if srt is not None and self.cfg.publish.upload_captions and job.format == VideoFormat.LONG:
            captions_set = self._set_captions(yt, video_id, srt, job.id)

        return UploadResult(video_id=video_id, url=url, thumbnail_set=thumbnail_set, captions_set=captions_set)

    def _set_thumbnail(self, yt, video_id: str, thumbnail: Path, job_id: str) -> bool:
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload

        try:
            yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumbnail))).execute()
            self.quota.record(self.cfg.quota.costs.thumbnails_set, "thumbnails.set", job_id)
            return True
        except HttpError as e:
            log.warning("Thumbnail upload failed (channel may not be verified): %s", e)
            return False

    def _set_captions(self, yt, video_id: str, srt_path: Path, job_id: str) -> bool:
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload

        try:
            yt.captions().insert(
                part="snippet",
                body={"snippet": {"videoId": video_id, "language": "en", "name": "English", "isDraft": False}},
                media_body=MediaFileUpload(str(srt_path)),
            ).execute()
            self.quota.record(self.cfg.quota.costs.captions_insert, "captions.insert", job_id)
            return True
        except HttpError as e:
            log.warning("Captions upload failed: %s", e)
            return False
