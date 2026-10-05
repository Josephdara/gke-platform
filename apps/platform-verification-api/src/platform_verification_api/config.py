"""Validated process configuration. Errors never echo environment values."""

from dataclasses import dataclass
import os
from collections.abc import Mapping


class ConfigurationError(ValueError):
    """A configuration field is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    service_name: str
    environment: str
    release_version: str
    port: int = 8080
    log_level: str = "INFO"
    secret_file: str | None = None

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

        port = text("APP_PORT", "8080")
        if not port.isascii() or not port.isdigit() or len(port) > 5:
            raise ConfigurationError("APP_PORT must be an integer from 1 to 65535")
        if not 1 <= int(port) <= 65535:
            raise ConfigurationError("APP_PORT must be an integer from 1 to 65535")

        log_level = text("LOG_LEVEL", "INFO").upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigurationError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")

        return cls(
            service_name=text("SERVICE_NAME", "platform-verification-api"),
            environment=text("ENVIRONMENT"),
            release_version=text("RELEASE_VERSION"),
            port=int(port),
            log_level=log_level,
            secret_file=None if values.get("SECRET_FILE") is None else text("SECRET_FILE"),
        )
