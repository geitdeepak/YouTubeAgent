"""Ollama LLM provider (LLD §8.1, LLR-LLM-02..06)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from edutube.config import LLMCfg
from edutube.errors import LLMOutputError, LLMUnavailableError
from edutube.llm.base import HealthStatus, LLMProvider, llm_schema, render_prompt
from edutube.logging_setup import get_logger

log = get_logger("llm.ollama")

T = TypeVar("T", bound=BaseModel)

MAX_ATTEMPTS = 3


class OllamaProvider(LLMProvider):
    def __init__(self, cfg: LLMCfg) -> None:
        self.cfg = cfg
        import ollama

        self.client = ollama.Client(host=cfg.host, timeout=cfg.timeout_s)

    def health(self) -> HealthStatus:
        try:
            models = self.client.list()
        except Exception as e:  # noqa: BLE001
            return HealthStatus(ok=False, detail=f"Ollama unreachable at {self.cfg.host}: {e}")
        names = [m.get("model") or m.get("name") for m in models.get("models", [])]
        if not any(self.cfg.model in (n or "") for n in names):
            return HealthStatus(
                ok=False, detail=f"Model '{self.cfg.model}' not pulled. Run: ollama pull {self.cfg.model}"
            )
        return HealthStatus(ok=True, detail=f"Ollama ready with model {self.cfg.model}")

    def generate_json(
        self,
        *,
        prompt_name: str,
        variables: dict[str, str],
        schema: type[T],
        temperature: float,
        log_dir: Path | None = None,
    ) -> T:
        system, user = render_prompt(prompt_name, variables)
        schema_json = llm_schema(schema)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        last_error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            start = time.monotonic()
            try:
                resp = self.client.chat(
                    model=self.cfg.model,
                    messages=messages,
                    format=schema_json,
                    options={"temperature": temperature, "num_ctx": self.cfg.num_ctx},
                )
            except ConnectionError as e:
                raise LLMUnavailableError(f"Cannot reach Ollama at {self.cfg.host}: {e}") from e
            except OSError as e:
                raise LLMUnavailableError(f"Cannot reach Ollama at {self.cfg.host}: {e}") from e

            duration = time.monotonic() - start
            raw = resp["message"]["content"]
            log.debug(
                "llm call model=%s prompt=%s attempt=%d duration=%.2fs",
                self.cfg.model,
                prompt_name,
                attempt,
                duration,
            )
            if log_dir is not None:
                _save_log(log_dir, prompt_name, attempt, messages, raw)

            try:
                return schema.model_validate_json(raw)
            except ValidationError as e:
                last_error = e
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {
                        "role": "user",
                        "content": f"Your JSON was invalid:\n{e}\nReturn corrected JSON only.",
                    }
                )
        raise LLMOutputError(f"Model returned invalid JSON for prompt '{prompt_name}': {last_error}")


def _save_log(log_dir: Path, prompt_name: str, attempt: int, messages: list[dict], raw: str) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    stem = prompt_name.replace(".md", "")
    existing = list(log_dir.glob(f"*_{stem}.json"))
    n = len(existing) + 1
    path = log_dir / f"{n}_{stem}_attempt{attempt}.json"
    path.write_text(
        json.dumps({"messages": messages, "response": raw}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
