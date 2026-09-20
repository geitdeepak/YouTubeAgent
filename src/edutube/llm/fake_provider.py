"""Fake LLM provider for offline tests (LLD §13)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from edutube.llm.base import HealthStatus, LLMProvider

T = TypeVar("T", bound=BaseModel)


class FakeLLMProvider(LLMProvider):
    """Returns pre-registered responses (or calls a factory) keyed by prompt name.

    Usage:
        fake = FakeLLMProvider()
        fake.register("script_short.md", lambda: Script(...))
    """

    def __init__(self) -> None:
        self._responses: dict[str, Callable[[], BaseModel]] = {}
        self.calls: list[dict] = []

    def register(self, prompt_name: str, factory: Callable[[], BaseModel]) -> None:
        self._responses[prompt_name] = factory

    def generate_json(
        self,
        *,
        prompt_name: str,
        variables: dict[str, str],
        schema: type[T],
        temperature: float,
        log_dir: Path | None = None,
    ) -> T:
        self.calls.append({"prompt_name": prompt_name, "variables": variables})
        if prompt_name not in self._responses:
            raise KeyError(f"FakeLLMProvider has no registered response for '{prompt_name}'")
        result = self._responses[prompt_name]()
        if not isinstance(result, schema):
            raise TypeError(f"Registered response for {prompt_name} is not a {schema.__name__}")
        return result

    def health(self) -> HealthStatus:
        return HealthStatus(ok=True, detail="fake provider always healthy")
