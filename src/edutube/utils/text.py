"""Text utilities: word counting, title normalization, slugs (LLD src layout)."""

from __future__ import annotations

import difflib
import re
import unicodedata

_WORD_RE = re.compile(r"\S+")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def count_words(text: str) -> int:
    """Count spoken words in ``text`` (whitespace-delimited tokens)."""
    if not text:
        return 0
    return len(_WORD_RE.findall(text))


def normalize_title(text: str) -> str:
    """Lowercase, strip punctuation and collapse whitespace (LLR-TOP-04)."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = _PUNCT_RE.sub("", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def title_similarity(a: str, b: str) -> float:
    """Fuzzy match ratio between two normalized titles (LLR-TOP-04)."""
    return difflib.SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio()


def slugify(text: str, max_len: int = 30) -> str:
    slug = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = _SLUG_RE.sub("-", slug.lower()).strip("-")
    return slug[:max_len].strip("-") or "topic"
