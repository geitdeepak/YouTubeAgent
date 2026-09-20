from __future__ import annotations

from edutube.utils.text import count_words, normalize_title, slugify, title_similarity


def test_count_words():
    assert count_words("Hello, world!") == 2
    assert count_words("") == 0
    assert count_words("   ") == 0
    assert count_words("one two   three") == 3


def test_normalize_title():
    assert normalize_title("What is RAG (Retrieval-Augmented Generation)?") == "what is rag retrievalaugmented generation"


def test_title_similarity_duplicate():
    ratio = title_similarity("What is a Neural Network?", "what is a neural network")
    assert ratio >= 0.85


def test_title_similarity_different():
    ratio = title_similarity("What is a Neural Network?", "How Transformers Work")
    assert ratio < 0.85


def test_slugify():
    assert slugify("What is RAG (Retrieval-Augmented Generation)?", 30) == "what-is-rag-retrieval-augmente"
    assert slugify("", 30) == "topic"
