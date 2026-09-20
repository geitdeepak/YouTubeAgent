"""FFmpeg/ffprobe subprocess wrapper (LLD §8.6, LLR-CMP-01, LLR-CMP-07)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from edutube.errors import FFmpegError
from edutube.logging_setup import get_logger

log = get_logger("media.ffmpeg")


def ffmpeg_bin() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def ffprobe_bin() -> str:
    return shutil.which("ffprobe") or "ffprobe"


def run(args: list[str], *, cwd: Path | None = None) -> str:
    """Run an ffmpeg/ffprobe command with list args, shell=False (LLR-CMP-01, NFR-04, C-03)."""
    log.debug("running: %s", " ".join(args))
    try:
        result = subprocess.run(
            args, cwd=cwd, shell=False, capture_output=True, text=True, check=False
        )
    except FileNotFoundError as e:
        raise FFmpegError(f"Executable not found: {args[0]}") from e
    if result.returncode != 0:
        stderr_tail = "\n".join(result.stderr.strip().splitlines()[-30:])
        raise FFmpegError(f"Command failed ({result.returncode}): {' '.join(args)}\n{stderr_tail}")
    return result.stdout


@dataclass
class StreamInfo:
    codec_type: str
    width: int | None = None
    height: int | None = None


@dataclass
class ProbeInfo:
    duration: float
    streams: list[StreamInfo]

    @property
    def video_streams(self) -> list[StreamInfo]:
        return [s for s in self.streams if s.codec_type == "video"]

    @property
    def audio_streams(self) -> list[StreamInfo]:
        return [s for s in self.streams if s.codec_type == "audio"]


def probe(path: Path) -> ProbeInfo:
    """ffprobe duration + stream info as JSON (LLD §8.6)."""
    out = run(
        [
            ffprobe_bin(),
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height",
            "-of",
            "json",
            str(path),
        ]
    )
    data = json.loads(out)
    duration = float(data.get("format", {}).get("duration", 0.0))
    streams = [
        StreamInfo(codec_type=s.get("codec_type", ""), width=s.get("width"), height=s.get("height"))
        for s in data.get("streams", [])
    ]
    return ProbeInfo(duration=duration, streams=streams)


_LUFS_RE = re.compile(r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS")


def loudness(path: Path) -> float:
    """Integrated loudness via ffmpeg ebur128 filter (LLR-CMP-09)."""
    args = [
        ffmpeg_bin(),
        "-i",
        str(path),
        "-af",
        "ebur128=framelog=quiet",
        "-f",
        "null",
        "-",
    ]
    try:
        result = subprocess.run(args, shell=False, capture_output=True, text=True, check=False)
    except FileNotFoundError as e:
        raise FFmpegError(f"Executable not found: {args[0]}") from e
    match = None
    for m in _LUFS_RE.finditer(result.stderr):
        match = m
    if match is None:
        raise FFmpegError(f"Could not parse loudness from ffmpeg output for {path}")
    return float(match.group(1))


def ff_filter_path(p: Path) -> str:
    """Escape a path for use inside an ffmpeg filter argument (LLR-CMP-07)."""
    s = str(p).replace("\\", "/")
    s = s.replace(":", "\\:")
    s = s.replace("'", "\\'")
    return s
