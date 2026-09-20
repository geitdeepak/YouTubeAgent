"""SQLite persistence layer (LLD §6, LLR-DB-01..04).

All database access goes through :class:`Repository`; no raw SQL outside this
module (LLR-DB-04).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from edutube.errors import NotFoundError
from edutube.models import Job, JobStatus, Topic, TopicFormat, TopicStatus, VideoFormat
from edutube.utils.text import normalize_title

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  title_norm TEXT NOT NULL,
  format TEXT NOT NULL CHECK (format IN ('short','long','both')),
  level TEXT NOT NULL DEFAULT 'beginner',
  priority INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
  keywords TEXT NOT NULL DEFAULT '[]',
  source_notes TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  reject_reason TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_topics_pick ON topics(status, priority DESC, created_at);

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  topic_id INTEGER NOT NULL REFERENCES topics(id),
  format TEXT NOT NULL,
  language TEXT NOT NULL,
  status TEXT NOT NULL,
  failed_stage TEXT,
  last_error TEXT,
  needs_human_review INTEGER NOT NULL DEFAULT 0,
  reject_reason TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS ix_jobs_topic ON jobs(topic_id, format);

CREATE TABLE IF NOT EXISTS stage_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES jobs(id),
  stage TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('running','done','failed','skipped')),
  started_at TEXT NOT NULL,
  finished_at TEXT,
  duration_s REAL,
  error TEXT
);

CREATE TABLE IF NOT EXISTS uploads (
  job_id TEXT PRIMARY KEY REFERENCES jobs(id),
  video_id TEXT NOT NULL UNIQUE,
  url TEXT NOT NULL,
  privacy TEXT NOT NULL,
  thumbnail_set INTEGER NOT NULL DEFAULT 0,
  captions_set INTEGER NOT NULL DEFAULT 0,
  uploaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quota_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  day_pt TEXT NOT NULL,
  op TEXT NOT NULL,
  units INTEGER NOT NULL,
  job_id TEXT,
  at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_quota_day ON quota_usage(day_pt);

CREATE TABLE IF NOT EXISTS asset_cache (
  key TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  meta TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_topic(row: sqlite3.Row) -> Topic:
    return Topic(
        id=row["id"],
        title=row["title"],
        format=TopicFormat(row["format"]),
        level=row["level"],
        priority=row["priority"],
        keywords=json.loads(row["keywords"]),
        source_notes=row["source_notes"],
        status=TopicStatus(row["status"]),
        reject_reason=row["reject_reason"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _row_to_job(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"],
        topic_id=row["topic_id"],
        format=VideoFormat(row["format"]),
        language=row["language"],
        status=JobStatus(row["status"]),
        failed_stage=row["failed_stage"],
        last_error=row["last_error"],
        needs_human_review=bool(row["needs_human_review"]),
        reject_reason=row["reject_reason"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


class Repository:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self) -> None:
        cur_version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if cur_version < SCHEMA_VERSION:
            with self.conn:
                self.conn.executescript(_SCHEMA)
                self.conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def close(self) -> None:
        self.conn.close()

    # ---- topics -----------------------------------------------------

    def add_topic(self, t: Topic) -> int:
        created_at = (t.created_at or datetime.now(UTC)).isoformat()
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO topics
                   (title, title_norm, format, level, priority, keywords,
                    source_notes, status, reject_reason, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    t.title,
                    normalize_title(t.title),
                    t.format.value,
                    t.level.value,
                    t.priority,
                    json.dumps(t.keywords),
                    t.source_notes,
                    t.status.value,
                    t.reject_reason,
                    created_at,
                ),
            )
        assert cur.lastrowid is not None
        return cur.lastrowid

    def list_topics(self, status: TopicStatus | None = None) -> list[Topic]:
        if status is None:
            rows = self.conn.execute("SELECT * FROM topics ORDER BY created_at DESC").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM topics WHERE status=? ORDER BY created_at DESC", (status.value,)
            ).fetchall()
        return [_row_to_topic(r) for r in rows]

    def get_topic(self, topic_id: int) -> Topic:
        row = self.conn.execute("SELECT * FROM topics WHERE id=?", (topic_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"Topic {topic_id} not found")
        return _row_to_topic(row)

    def find_similar_titles(self, title: str, min_ratio: float = 0.85) -> list[str]:
        from edutube.utils.text import title_similarity

        rows = self.conn.execute("SELECT title FROM topics").fetchall()
        return [r["title"] for r in rows if title_similarity(title, r["title"]) >= min_ratio]

    def set_topic_status(self, topic_id: int, status: TopicStatus, reason: str | None = None) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE topics SET status=?, reject_reason=? WHERE id=?",
                (status.value, reason, topic_id),
            )

    def next_topic(self, fmt: VideoFormat) -> Topic | None:
        """LLR-TOP-03: highest priority, then oldest created_at, format matches (or 'both'),
        and no job in this format with status not in (FAILED, REJECTED)."""
        row = self.conn.execute(
            """SELECT t.* FROM topics t
               WHERE t.status = 'active'
                 AND t.format IN (?, 'both')
                 AND NOT EXISTS (
                   SELECT 1 FROM jobs j WHERE j.topic_id = t.id AND j.format = ?
                     AND j.status NOT IN ('FAILED','REJECTED'))
               ORDER BY t.priority DESC, t.created_at ASC
               LIMIT 1""",
            (fmt.value, fmt.value),
        ).fetchone()
        return _row_to_topic(row) if row else None

    # ---- jobs ---------------------------------------------------------

    def create_job(self, job: Job) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO jobs
                   (id, topic_id, format, language, status, failed_stage, last_error,
                    needs_human_review, reject_reason, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    job.id,
                    job.topic_id,
                    job.format.value,
                    job.language,
                    job.status.value,
                    job.failed_stage,
                    job.last_error,
                    int(job.needs_human_review),
                    job.reject_reason,
                    job.created_at.isoformat(),
                    job.updated_at.isoformat(),
                ),
            )

    def get_job(self, job_id: str) -> Job:
        row = self.conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"Job {job_id} not found")
        return _row_to_job(row)

    def list_jobs(self, status: JobStatus | None = None, limit: int = 50) -> list[Job]:
        if status is None:
            rows = self.conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM jobs WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status.value, limit),
            ).fetchall()
        return [_row_to_job(r) for r in rows]

    def update_job(self, job_id: str, **fields: object) -> None:
        if not fields:
            return
        cols = []
        vals: list[object] = []
        for k, v in fields.items():
            cols.append(f"{k}=?")
            if hasattr(v, "value"):  # enum
                v = v.value  # noqa: PLW2901
            if isinstance(v, bool):
                v = int(v)  # noqa: PLW2901
            vals.append(v)
        cols.append("updated_at=?")
        vals.append(_now_iso())
        vals.append(job_id)
        with self.conn:
            self.conn.execute(f"UPDATE jobs SET {', '.join(cols)} WHERE id=?", vals)

    # ---- stage runs -----------------------------------------------------

    def start_stage(self, job_id: str, stage: str) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO stage_runs (job_id, stage, status, started_at) VALUES (?,?,?,?)",
                (job_id, stage, "running", _now_iso()),
            )
        assert cur.lastrowid is not None
        return cur.lastrowid

    def finish_stage(self, run_id: int, status: str, error: str | None = None) -> None:
        row = self.conn.execute(
            "SELECT started_at FROM stage_runs WHERE id=?", (run_id,)
        ).fetchone()
        duration = None
        if row:
            started = datetime.fromisoformat(row["started_at"])
            duration = (datetime.now(UTC) - started.astimezone(UTC)).total_seconds()
        with self.conn:
            self.conn.execute(
                "UPDATE stage_runs SET status=?, finished_at=?, duration_s=?, error=? WHERE id=?",
                (status, _now_iso(), duration, error, run_id),
            )

    def list_stage_runs(self, job_id: str) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM stage_runs WHERE job_id=? ORDER BY id ASC", (job_id,)
            ).fetchall()
        )

    # ---- uploads / quota / cache -----------------------------------------

    def record_upload(
        self, job_id: str, video_id: str, url: str, privacy: str,
        thumbnail_set: bool = False, captions_set: bool = False,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO uploads (job_id, video_id, url, privacy, thumbnail_set,
                                        captions_set, uploaded_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (job_id, video_id, url, privacy, int(thumbnail_set), int(captions_set), _now_iso()),
            )

    def get_upload(self, job_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM uploads WHERE job_id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def add_quota(self, day_pt: str, op: str, units: int, job_id: str | None) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO quota_usage (day_pt, op, units, job_id, at) VALUES (?,?,?,?,?)",
                (day_pt, op, units, job_id, _now_iso()),
            )

    def quota_used(self, day_pt: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(units),0) AS total FROM quota_usage WHERE day_pt=?", (day_pt,)
        ).fetchone()
        return int(row["total"])

    def cache_get(self, key: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM asset_cache WHERE key=?", (key,)).fetchone()
        if row is None:
            return None
        return {"key": row["key"], "path": row["path"], "meta": json.loads(row["meta"])}

    def cache_put(self, key: str, path: str, meta: dict) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO asset_cache (key, path, meta, created_at) VALUES (?,?,?,?)",
                (key, path, json.dumps(meta), _now_iso()),
            )
