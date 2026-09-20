"""Text-to-speech + word alignment (LLD §8.2, LLR-TTS-01..06)."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import time
from abc import ABC, abstractmethod
from pathlib import Path

from edutube.errors import ServiceUnavailableError
from edutube.logging_setup import get_logger
from edutube.media import ffmpeg
from edutube.models import Word

log = get_logger("media.tts")

RETRY_DELAYS = (2, 4, 8)  # LLR-TTS-05

DEFAULT_VOICES = {
    "en": {"primary": "en-IN-PrabhatNeural", "alt": "en-IN-NeerjaNeural"},
    "hi": {"primary": "hi-IN-MadhurNeural", "alt": "hi-IN-SwaraNeural"},
}


def apply_pronunciations(text: str, pronunciations: dict[str, str]) -> str:
    """Whole-word, case-sensitive regex replacement on the spoken text (LLR-TTS-03)."""
    if not pronunciations:
        return text
    pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in pronunciations) + r")\b")
    return pattern.sub(lambda m: pronunciations[m.group(0)], text)


def _expansions(display_text: str, pronunciations: dict[str, str]) -> list[int]:
    exps = []
    for w in display_text.split():
        core = re.sub(r"^\W+|\W+$", "", w)
        exps.append(len(pronunciations[core].split()) if core in pronunciations else 1)
    return exps


def remap_to_display_words(
    spoken_words: list[Word], display_text: str, pronunciations: dict[str, str]
) -> list[Word]:
    """Map spoken-word timings back onto the original display words (LLR-TTS-03)."""
    display_tokens = display_text.split()
    exps = _expansions(display_text, pronunciations)
    result: list[Word] = []
    idx = 0
    for token, exp in zip(display_tokens, exps, strict=True):
        group = spoken_words[idx : idx + exp]
        if not group:
            start = spoken_words[-1].end if spoken_words else 0.0
            result.append(Word(word=token, start=start, end=start))
        else:
            result.append(Word(word=token, start=group[0].start, end=group[-1].end))
        idx += exp
    return result


class Aligner:
    """Word-timing fallback: faster-whisper if available, else even distribution (LLR-TTS-02)."""

    def __init__(self, fallback: str = "faster-whisper") -> None:
        self.fallback = fallback

    def align(self, audio_path: Path, spoken_text: str) -> list[Word]:
        expected = spoken_text.split()
        if not expected:
            return []
        if self.fallback == "faster-whisper":
            try:
                whisper_words = self._faster_whisper_words(audio_path)
                if whisper_words:
                    return self._resample_to_count(whisper_words, expected)
            except ImportError:
                log.warning("faster-whisper not installed; falling back to even distribution")
            except Exception as e:  # noqa: BLE001
                log.warning("faster-whisper alignment failed (%s); falling back to even distribution", e)
        return self._even_distribution(audio_path, expected)

    def _faster_whisper_words(self, audio_path: Path) -> list[Word]:
        from faster_whisper import WhisperModel

        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(audio_path), word_timestamps=True)
        words: list[Word] = []
        for seg in segments:
            for w in seg.words or []:
                words.append(Word(word=(w.word or "").strip(), start=w.start, end=w.end))
        return words

    def _resample_to_count(self, whisper_words: list[Word], expected: list[str]) -> list[Word]:
        start = whisper_words[0].start
        end = whisper_words[-1].end
        n = len(expected)
        step = (end - start) / n if n else 0.0
        return [Word(word=w, start=start + i * step, end=start + (i + 1) * step) for i, w in enumerate(expected)]

    def _even_distribution(self, audio_path: Path, expected: list[str]) -> list[Word]:
        duration = ffmpeg.probe(audio_path).duration
        n = len(expected)
        step = duration / n if n else 0.0
        return [Word(word=w, start=i * step, end=(i + 1) * step) for i, w in enumerate(expected)]


class TTSProvider(ABC):
    @abstractmethod
    def synthesize(
        self, text: str, out_mp3: Path, *, voice: str, rate: str, pitch: str
    ) -> list[Word]: ...


async def _stream(spoken: str, out_mp3: Path, voice: str, rate: str, pitch: str) -> list[Word]:
    import edge_tts

    kwargs: dict[str, str] = {}
    sig = inspect.signature(edge_tts.Communicate.__init__)
    if "boundary" in sig.parameters:
        kwargs["boundary"] = "WordBoundary"

    comm = edge_tts.Communicate(spoken, voice, rate=rate, pitch=pitch, **kwargs)  # type: ignore[arg-type]
    words: list[Word] = []
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    with open(out_mp3, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                s = chunk["offset"] / 1e7
                d = chunk["duration"] / 1e7
                words.append(Word(word=chunk["text"], start=s, end=s + d))
    return words


def _synthesize_with_retry(spoken: str, out_mp3: Path, voice: str, rate: str, pitch: str) -> list[Word]:
    last_exc: Exception | None = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            return asyncio.run(_stream(spoken, out_mp3, voice, rate, pitch))
        except Exception as e:  # noqa: BLE001
            last_exc = e
            if attempt < len(RETRY_DELAYS):
                log.warning("edge-tts attempt %d failed (%s), retrying", attempt + 1, e)
                time.sleep(RETRY_DELAYS[attempt])
    raise ServiceUnavailableError(f"edge-tts failed after retries: {last_exc}") from last_exc


class EdgeTTSProvider(TTSProvider):
    def __init__(self, pronunciations: dict[str, str], aligner_fallback: str = "faster-whisper") -> None:
        self.pronunciations = pronunciations
        self.aligner = Aligner(aligner_fallback)

    def synthesize(self, text: str, out_mp3: Path, *, voice: str, rate: str, pitch: str) -> list[Word]:
        spoken = apply_pronunciations(text, self.pronunciations)
        words = _synthesize_with_retry(spoken, out_mp3, voice, rate, pitch)
        if not words:
            words = self.aligner.align(out_mp3, spoken)
        return remap_to_display_words(words, text, self.pronunciations)


class FakeTTSProvider(TTSProvider):
    """Generates a sine-tone mp3 of the right length via real ffmpeg (LLD §13 integration tests)."""

    def __init__(self, words_per_second: float = 2.5) -> None:
        self.words_per_second = words_per_second

    def synthesize(self, text: str, out_mp3: Path, *, voice: str, rate: str, pitch: str) -> list[Word]:
        words_list = text.split()
        n = len(words_list)
        duration = max(n / self.words_per_second, 0.5)
        out_mp3.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg.run(
            [
                ffmpeg.ffmpeg_bin(),
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=440:duration={duration}",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "128k",
                str(out_mp3),
            ]
        )
        step = duration / n if n else 0.0
        return [Word(word=w, start=i * step, end=(i + 1) * step) for i, w in enumerate(words_list)]


def save_words(words: list[Word], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([w.model_dump() for w in words], indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_words(path: Path) -> list[Word]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Word(**w) for w in data]
