"""LLM provider interface (LLD §8.1, LLR-LLM-01)."""

from __future__ import annotations

import string
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass
class HealthStatus:
    ok: bool
    detail: str = ""


class LLMProvider(ABC):
    """Abstract LLM provider: structured JSON generation + health check."""

    @abstractmethod
    def generate_json(
        self,
        *,
        prompt_name: str,
        variables: dict[str, str],
        schema: type[T],
        temperature: float,
        log_dir: Path | None = None,
    ) -> T:
        """Render prompts/<prompt_name>.md, call the model, validate the JSON response as `schema`."""

    @abstractmethod
    def health(self) -> HealthStatus:
        """Check that the provider is reachable and ready."""


def render_prompt(prompt_name: str, variables: dict[str, str]) -> tuple[str, str]:
    """Render a Markdown prompt template split on the line '---USER---' (LLR-LLM-05)."""
    path = PROMPTS_DIR / prompt_name
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    raw = path.read_text(encoding="utf-8")
    if "---USER---" not in raw:
        raise ValueError(f"Prompt {prompt_name} is missing the '---USER---' separator")
    system_tpl, user_tpl = raw.split("---USER---", 1)
    system = string.Template(system_tpl.strip()).safe_substitute(variables)
    user = string.Template(user_tpl.strip()).safe_substitute(variables)
    return system, user


def llm_schema(schema: type[BaseModel]) -> dict:
    """A simplified JSON schema (no $defs refs collapsed further) for the LLM's `format` arg."""
    return schema.model_json_schema()
