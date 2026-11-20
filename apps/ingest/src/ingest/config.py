"""Validated job configuration. Errors never echo environment values."""

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


class ConfigurationError(ValueError):
    """A configuration field is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    environment: str
    release_version: str
    # gs://<bucket>/<prefix>/ for the cluster, or a local directory for the Compose stack.
    corpus_source: str
    embeddings_url: str
    database_host: str
    database_password_file: str
    database_port: int = 5432
    database_name: str = "rag"
    database_user: str = "ingest"
    # Evidence bucket for the run report. Unset, the report goes to the log only.
    report_bucket: str | None = None
    report_prefix: str = "inference/ingest/"
    chunk_tokens: int = 300
    overlap_tokens: int = 40
    embed_batch: int = 16
    max_file_bytes: int = 2_000_000
    parse_seconds: int = 10
    embedding_model: str = "bge-small-en-v1.5"
    embedding_revision: str = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
    embedding_dimensions: int = 384
    migrations_dir: Path = MIGRATIONS_DIR

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
            if not value.isascii() or not value.isdigit() or len(value) > 9 or not low <= int(value) <= high:
                raise ConfigurationError(f"{name} must be an integer from {low} to {high}")
            return int(value)

        def url(name: str) -> str:
            value = text(name).rstrip("/")
            if not value.startswith(("http://", "https://")) or " " in value:
                raise ConfigurationError(f"{name} must be an http:// or https:// URL")
            return value

        source = text("CORPUS_SOURCE")
        if source.startswith("gs://") and not source.endswith("/"):
            source += "/"

        chunk_tokens = integer("CHUNK_TOKENS", 300, 50, 480)
        overlap = integer("OVERLAP_TOKENS", 40, 0, 200)
        if overlap >= chunk_tokens // 2:
            raise ConfigurationError("OVERLAP_TOKENS must be less than half of CHUNK_TOKENS")

        report_bucket = values.get("REPORT_BUCKET")
        return cls(
            environment=text("ENVIRONMENT"),
            release_version=text("RELEASE_VERSION"),
            corpus_source=source,
            embeddings_url=url("EMBEDDINGS_URL"),
            database_host=text("DATABASE_HOST"),
            database_password_file=text("DATABASE_PASSWORD_FILE"),
            database_port=integer("DATABASE_PORT", 5432, 1, 65535),
            database_name=text("DATABASE_NAME", "rag"),
            database_user=text("DATABASE_USER", "ingest"),
            report_bucket=None if report_bucket is None else text("REPORT_BUCKET"),
            chunk_tokens=chunk_tokens,
            overlap_tokens=overlap,
            embed_batch=integer("EMBED_BATCH", 16, 1, 32),
            max_file_bytes=integer("MAX_FILE_BYTES", 2_000_000, 1, 50_000_000),
            parse_seconds=integer("PARSE_SECONDS", 10, 1, 300),
        )
