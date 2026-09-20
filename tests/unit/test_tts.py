from __future__ import annotations

from edutube.media.tts import apply_pronunciations, remap_to_display_words
from edutube.models import Word

PRONUNCIATIONS = {"LLM": "L L M", "GPT": "G P T"}


def test_apply_pronunciations_whole_word_only():
    text = "An LLM is not the same as LLMs or a GPT."
    spoken = apply_pronunciations(text, PRONUNCIATIONS)
    assert spoken == "An L L M is not the same as LLMs or a G P T."


def test_remap_to_display_words_merges_expanded_spoken_words():
    display_text = "An LLM is great"
    spoken_words = [
        Word(word="An", start=0.0, end=0.2),
        Word(word="L", start=0.2, end=0.4),
        Word(word="L", start=0.4, end=0.6),
        Word(word="M", start=0.6, end=0.9),
        Word(word="is", start=0.9, end=1.1),
        Word(word="great", start=1.1, end=1.5),
    ]
    result = remap_to_display_words(spoken_words, display_text, PRONUNCIATIONS)
    assert [w.word for w in result] == ["An", "LLM", "is", "great"]
    assert result[1].start == 0.2
    assert result[1].end == 0.9


def test_remap_to_display_words_identity_when_no_pronunciations():
    display_text = "Hello world"
    spoken_words = [Word(word="Hello", start=0.0, end=0.5), Word(word="world", start=0.5, end=1.0)]
    result = remap_to_display_words(spoken_words, display_text, {})
    assert [w.word for w in result] == ["Hello", "world"]
