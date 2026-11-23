"""Validated process configuration. Errors never echo environment values."""

from collections.abc import Mapping
from dataclasses import dataclass
import os

from .guardrails import TEMPLATE


class ConfigurationError(ValueError):
    """A configuration field is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    environment: str
    release_version: str
    model_url: str
    # Sign-in: the users file with scrypt hashes, and the key that signs session cookies.
    users_file: str
    session_key_file: str
    # The site's own origin. State-changing requests must send exactly this Origin.
    allowed_origin: str
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
    # Longest wait for the first token. It covers queueing behind busy slots and prompt processing,
    # which on CPU can take longer than the gap between later tokens.
    first_token_timeout_seconds: int = 90
    context_tokens: int = 4096
    output_tokens: int = 384
    passage_tokens: int = 1200
    history_turns: int = 2
    max_input_chars: int = 2000
    rate_limit_per_minute: int = 10
    # Retrieval is on when a database host is set; without one, every question gets no passages.
    database_host: str | None = None
    database_port: int = 5432
    database_name: str = "rag"
    database_user: str = "rag_api"
    database_password_file: str | None = None
    embeddings_url: str | None = None
    retrieval_top_k: int = 5
    # Cosine similarities measured with bge-small on this corpus: off-topic messages ("ping",
    # "write me a poem") score at most 0.60 at best, documentation questions at least 0.69.
    # A question whose best passage is below relevance_floor gets no passages and a general
    # answer; below similarity_floor, a single passage is dropped.
    relevance_floor: float = 0.65
    similarity_floor: float = 0.60
    # bge-small-en-v1.5's instruction for short queries that retrieve longer passages.
    query_prefix: str = "Represent this sentence for searching relevant passages: "
    embedding_model: str = "bge-small-en-v1.5"
    embedding_revision: str = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
    embedding_dimensions: int = 384
    # Secure cookies need HTTPS; only a local http:// run turns this off.
    cookie_secure: bool = True
    session_hours: int = 8
    login_attempts_per_minute: int = 5
    # X-Forwarded-For entries the load balancer appends: 2 behind GKE's external Application
    # Load Balancer, 0 when nothing sits in front.
    forwarded_hops: int = 0
    # The built frontend. Unset, rag-api serves the API only.
    static_dir: str | None = None
    # Model Armor: off, inspect (screen and record), or block (refuse flagged questions, drop
    # flagged passages, withhold flagged answers), with the template's full resource name.
    model_armor_mode: str = "off"
    model_armor_template: str | None = None

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

        database_host = None if values.get("DATABASE_HOST") is None else text("DATABASE_HOST")
        database_password_file = embeddings_url = None
        if database_host is not None:
            database_password_file = text("DATABASE_PASSWORD_FILE")
            embeddings_url = text("EMBEDDINGS_URL").rstrip("/")
            if not embeddings_url.startswith(("http://", "https://")) or " " in embeddings_url:
                raise ConfigurationError("EMBEDDINGS_URL must be an http:// or https:// URL")
        allowed_origin = text("ALLOWED_ORIGIN").rstrip("/")
        scheme, _, rest = allowed_origin.partition("://")
        if scheme not in ("http", "https") or not rest or "/" in rest or " " in rest:
            raise ConfigurationError("ALLOWED_ORIGIN must be a scheme and host, such as https://assistant.example.com")
        secure = text("COOKIE_SECURE", "true").lower()
        if secure not in ("true", "false"):
            raise ConfigurationError("COOKIE_SECURE must be true or false")
        if secure == "true" and scheme != "https":
            raise ConfigurationError("COOKIE_SECURE=true needs an https ALLOWED_ORIGIN")

        def fraction(name: str, default: str) -> float:
            try:
                value = float(text(name, default))
            except ValueError:
                value = -1.0
            if not 0.0 <= value < 1.0:
                raise ConfigurationError(f"{name} must be a number from 0 up to 1")
            return value

        model_armor_mode = text("MODEL_ARMOR_MODE", "off").lower()
        if model_armor_mode not in ("off", "inspect", "block"):
            raise ConfigurationError("MODEL_ARMOR_MODE must be off, inspect, or block")
        model_armor_template = None
        if model_armor_mode != "off":
            model_armor_template = text("MODEL_ARMOR_TEMPLATE")
            if not TEMPLATE.fullmatch(model_armor_template):
                raise ConfigurationError("MODEL_ARMOR_TEMPLATE must be projects/PROJECT/locations/LOCATION/templates/TEMPLATE")

        settings = cls(
            environment=text("ENVIRONMENT"),
            release_version=text("RELEASE_VERSION"),
            model_url=model_url,
            users_file=text("USERS_FILE"),
            session_key_file=text("SESSION_KEY_FILE"),
            allowed_origin=allowed_origin,
            cookie_secure=secure == "true",
            session_hours=integer("SESSION_HOURS", 8, 1, 24),
            login_attempts_per_minute=integer("LOGIN_ATTEMPTS_PER_MINUTE", 5, 1, 100),
            forwarded_hops=integer("FORWARDED_HOPS", 0, 0, 5),
            static_dir=None if values.get("STATIC_DIR") is None else text("STATIC_DIR"),
            service_name=text("SERVICE_NAME", "rag-api"),
            port=app_port,
            metrics_port=metrics_port,
            log_level=log_level,
            model_alias=text("MODEL_ALIAS", "assistant-chat"),
            admission_limit=integer("ADMISSION_LIMIT", 3, 1, 64),
            request_deadline_seconds=integer("REQUEST_DEADLINE_SECONDS", 120, 10, 600),
            stall_timeout_seconds=integer("STALL_TIMEOUT_SECONDS", 30, 1, 300),
            first_token_timeout_seconds=integer("FIRST_TOKEN_TIMEOUT_SECONDS", 90, 1, 600),
            context_tokens=integer("CONTEXT_TOKENS", 4096, 512, 131072),
            output_tokens=integer("OUTPUT_TOKENS", 384, 16, 8192),
            passage_tokens=integer("PASSAGE_TOKENS", 1200, 0, 65536),
            history_turns=integer("HISTORY_TURNS", 2, 0, 10),
            max_input_chars=integer("MAX_INPUT_CHARS", 2000, 1, 20000),
            rate_limit_per_minute=integer("RATE_LIMIT_PER_MINUTE", 10, 1, 1000),
            database_host=database_host,
            database_port=integer("DATABASE_PORT", 5432, 1, 65535),
            database_name=text("DATABASE_NAME", "rag"),
            database_user=text("DATABASE_USER", "rag_api"),
            database_password_file=database_password_file,
            embeddings_url=embeddings_url,
            retrieval_top_k=integer("RETRIEVAL_TOP_K", 5, 1, 5),
            relevance_floor=fraction("RELEVANCE_FLOOR", "0.65"),
            similarity_floor=fraction("SIMILARITY_FLOOR", "0.60"),
            model_armor_mode=model_armor_mode,
            model_armor_template=model_armor_template,
        )
        if settings.output_tokens + settings.passage_tokens >= settings.context_tokens:
            raise ConfigurationError("OUTPUT_TOKENS plus PASSAGE_TOKENS must be less than CONTEXT_TOKENS")
        if settings.stall_timeout_seconds >= settings.request_deadline_seconds:
            raise ConfigurationError("STALL_TIMEOUT_SECONDS must be less than REQUEST_DEADLINE_SECONDS")
        if not settings.stall_timeout_seconds <= settings.first_token_timeout_seconds < settings.request_deadline_seconds:
            raise ConfigurationError("FIRST_TOKEN_TIMEOUT_SECONDS must be at least STALL_TIMEOUT_SECONDS "
                                     "and less than REQUEST_DEADLINE_SECONDS")
        return settings
