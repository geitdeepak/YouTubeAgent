"""Error hierarchy for EduTube Agent (LLD §9).

Every user-facing failure derives from :class:`EdutubeError` and carries an
``exit_code`` (LLR-CLI-03) and an optional ``hint`` printed by the CLI as
"-> Fix: <hint>" (LLR-CLI-04, NFR-08).
"""

from __future__ import annotations


class EdutubeError(Exception):
    """Base class for all EduTube errors."""

    exit_code: int = 1
    hint: str = ""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if hint is not None:
            self.hint = hint


class ConfigError(EdutubeError):
    exit_code = 2


class ServiceUnavailableError(EdutubeError):
    exit_code = 3


class LLMUnavailableError(ServiceUnavailableError):
    hint = "Start Ollama: `ollama serve`, then `ollama pull <model>`"


class LLMOutputError(EdutubeError):
    hint = "Try a larger model (llama3.1:8b/qwen2.5:7b) or lower temperature"


class ScriptLengthError(EdutubeError):
    hint = "Run `edutube edit-script <id>` or `edutube resume <id> --from-stage script`"


class DurationFitError(EdutubeError):
    hint = "Edit narration length, then `edutube resume <id> --from-stage voice`"


class FFmpegError(EdutubeError):
    hint = "Run `edutube doctor`; see job.log for the ffmpeg command"


class RenderValidationError(EdutubeError):
    hint = "See render.json and job.log for details"


class AuthExpiredError(EdutubeError):
    hint = "Run `edutube auth`. Set the OAuth consent screen to 'In production'"


class UploadError(EdutubeError):
    pass


class QuotaExhaustedError(EdutubeError):
    exit_code = 4
    hint = "Quota resets at midnight Pacific Time"


class StageFailedError(EdutubeError):
    """Wraps the stage name and underlying cause of a pipeline failure."""

    def __init__(self, stage: str, cause: Exception) -> None:
        hint = getattr(cause, "hint", "") or "See job.log for details"
        super().__init__(f"stage '{stage}' failed: {cause}", hint=hint)
        self.stage = stage
        self.cause = cause


class NotFoundError(EdutubeError):
    """Raised when a job/topic/upload lookup fails."""

    exit_code = 1
