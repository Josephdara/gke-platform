"""Validated process configuration. Errors never echo environment values."""

from collections.abc import Mapping
from dataclasses import dataclass
import os


class ConfigurationError(ValueError):
    """A configuration field is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    environment: str
    release_version: str
    model_url: str
    service_name: str = "rag-api"
    port: int = 8080
    metrics_port: int = 9090
    log_level: str = "INFO"
    model_alias: str = "assistant-chat"
    # Generations one replica runs at once; requests beyond it get 429.
    admission_limit: int = 3
    request_deadline_seconds: int = 120
    # Longest wait for the next token before the stream fails as stalled.
    stall_timeout_seconds: int = 30
    context_tokens: int = 4096
    output_tokens: int = 384
    passage_tokens: int = 1200
    history_turns: int = 2
    max_input_chars: int = 2000
    rate_limit_per_minute: int = 10

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        values = os.environ if environ is None else environ

        def text(name: str, default: str | None = None) -> str:
            value = values.get(name, default)
            if value is None or not value.strip():
                raise ConfigurationError(f"{name} must be nonempty")
            if any(ord(char) < 32 or ord(char) == 127 for char in value):
                raise ConfigurationError(f"{name} must not contain control characters")
            return value.strip()

        def integer(name: str, default: int, low: int, high: int) -> int:
            value = text(name, str(default))
            if not value.isascii() or not value.isdigit() or len(value) > 6 or not low <= int(value) <= high:
                raise ConfigurationError(f"{name} must be an integer from {low} to {high}")
            return int(value)

        app_port = integer("APP_PORT", 8080, 1, 65535)
        metrics_port = integer("METRICS_PORT", 9090, 1, 65535)
        if metrics_port == app_port:
            raise ConfigurationError("METRICS_PORT must differ from APP_PORT")

        log_level = text("LOG_LEVEL", "INFO").upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigurationError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")

        model_url = text("MODEL_URL").rstrip("/")
        if not model_url.startswith(("http://", "https://")) or " " in model_url:
            raise ConfigurationError("MODEL_URL must be an http:// or https:// URL")

        settings = cls(
            environment=text("ENVIRONMENT"),
            release_version=text("RELEASE_VERSION"),
            model_url=model_url,
            service_name=text("SERVICE_NAME", "rag-api"),
            port=app_port,
            metrics_port=metrics_port,
            log_level=log_level,
            model_alias=text("MODEL_ALIAS", "assistant-chat"),
            admission_limit=integer("ADMISSION_LIMIT", 3, 1, 64),
            request_deadline_seconds=integer("REQUEST_DEADLINE_SECONDS", 120, 10, 600),
            stall_timeout_seconds=integer("STALL_TIMEOUT_SECONDS", 30, 1, 300),
            context_tokens=integer("CONTEXT_TOKENS", 4096, 512, 131072),
            output_tokens=integer("OUTPUT_TOKENS", 384, 16, 8192),
            passage_tokens=integer("PASSAGE_TOKENS", 1200, 0, 65536),
            history_turns=integer("HISTORY_TURNS", 2, 0, 10),
            max_input_chars=integer("MAX_INPUT_CHARS", 2000, 1, 20000),
            rate_limit_per_minute=integer("RATE_LIMIT_PER_MINUTE", 10, 1, 1000),
        )
        if settings.output_tokens + settings.passage_tokens >= settings.context_tokens:
            raise ConfigurationError("OUTPUT_TOKENS plus PASSAGE_TOKENS must be less than CONTEXT_TOKENS")
        if settings.stall_timeout_seconds >= settings.request_deadline_seconds:
            raise ConfigurationError("STALL_TIMEOUT_SECONDS must be less than REQUEST_DEADLINE_SECONDS")
        return settings
