"""JSON logging and request instrumentation without request payloads."""

from datetime import datetime, timezone
import json
import logging
import re
import sys
import time
from typing import TextIO
from uuid import uuid4

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Settings

REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
# Kubernetes probes call these every few seconds; successful checks are logged at DEBUG.
HEALTH_PATHS = frozenset({"/livez", "/readyz"})
READINESS_PATH = "/readyz"


def request_level(path: str, status: int, failed: bool) -> int:
    if failed:
        return logging.ERROR
    if path == READINESS_PATH and status == 503:
        # Not ready is an expected state, not a server fault.
        return logging.WARNING
    if status >= 500:
        return logging.ERROR
    if status >= 400:
        return logging.WARNING
    return logging.DEBUG if path in HEALTH_PATHS else logging.INFO


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str, environment: str, release: str):
        super().__init__()
        self.identity = {"service": service, "environment": environment, "release": release}

    def format(self, record: logging.LogRecord) -> str:
        data = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "severity": record.levelname,
            **self.identity,
            "event": record.getMessage(),
        }
        # Exception text can contain input or secret values; only its class is logged.
        for key in ("request_id", "method", "path", "status", "duration_ms", "error_type"):
            if hasattr(record, key):
                data[key] = getattr(record, key)
        return json.dumps(data, ensure_ascii=True)


def create_logger(settings: Settings, stream: TextIO | None = None) -> logging.Logger:
    logger = logging.Logger("platform_verification_api", level=settings.log_level)
    logger.propagate = False
    handler = logging.StreamHandler(sys.stdout if stream is None else stream)
    handler.setFormatter(JsonFormatter(settings.service_name, settings.environment, settings.release_version))
    logger.addHandler(handler)
    return logger


def server_log_config(settings: Settings) -> dict:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"json": {
            "()": JsonFormatter,
            "service": settings.service_name,
            "environment": settings.environment,
            "release": settings.release_version,
        }},
        "handlers": {"stdout": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "json",
        }},
        "loggers": {name: {
            "handlers": ["stdout"], "level": settings.log_level, "propagate": False,
        } for name in ("uvicorn", "uvicorn.error", "uvicorn.access")},
    }


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp, logger: logging.Logger):
        self.app = app
        self.logger = logger

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        supplied = [value.decode("latin-1") for key, value in scope["headers"] if key.lower() == b"x-request-id"]
        request_id = supplied[0] if len(supplied) == 1 and REQUEST_ID.fullmatch(supplied[0]) else str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.perf_counter()
        status = 500
        response_started = False
        error_type = None

        async def respond(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status = message["status"]
                response_started = True
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, respond)
        except Exception as exc:
            error_type = type(exc).__name__
            if response_started:
                raise
            await JSONResponse({"detail": "Internal server error"}, status_code=500)(scope, receive, respond)
        finally:
            level = request_level(scope["path"], status, error_type is not None)
            fields = {
                "request_id": request_id,
                "method": scope["method"],
                "path": scope["path"],
                "status": status,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            }
            if error_type:
                fields["error_type"] = error_type
            self.logger.log(level, "http_request", extra=fields)
