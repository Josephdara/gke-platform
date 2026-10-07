"""Server entry point for local execution and future container packaging."""

import json
import sys

import uvicorn
from fastapi import FastAPI
from prometheus_client import start_http_server

from .app import create_app
from .config import ConfigurationError, Settings
from .logging import server_log_config

GRACEFUL_SHUTDOWN_SECONDS = 20  # Leaves headroom in Kubernetes' 30-second grace period.


def build_server(app: FastAPI, settings: Settings) -> uvicorn.Server:
    return uvicorn.Server(uvicorn.Config(
        app,
        host="0.0.0.0",
        port=settings.port,
        access_log=False,
        log_config=server_log_config(settings),
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS,
        server_header=False,
    ))


def main() -> None:
    try:
        settings = Settings.from_env()
    except ConfigurationError as exc:
        print(json.dumps({"severity": "ERROR", "event": "configuration_error", "message": str(exc)}), file=sys.stderr)
        raise SystemExit(2) from None

    server = build_server(create_app(settings), settings)
    start_http_server(settings.metrics_port)
    try:
        server.run()
    except KeyboardInterrupt:
        raise SystemExit(130) from None
