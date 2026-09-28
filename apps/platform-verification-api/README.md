# Platform Verification API

A small Python HTTP API used to verify the GKE platform's deployment, health, configuration, and logging behavior. FastAPI handles requests; Uvicorn manages the server lifecycle. This component covers Phase 2 steps 1 through 4. Container packaging and image scanning follow separately.

## Layout

| Module | Responsibility |
| --- | --- |
| `src/platform_verification_api/app.py` | Application factory, startup, and shutdown |
| `src/platform_verification_api/routes.py` | Service identity and health endpoints |
| `src/platform_verification_api/config.py` | Environment configuration and validation |
| `src/platform_verification_api/logging.py` | JSON logs and request IDs |
| `src/platform_verification_api/server.py` | Uvicorn configuration and entry point |
| `tests/` | Configuration, endpoint, logging, lifecycle, and process tests |

## HTTP interface

| Endpoint | Response |
| --- | --- |
| `GET /` | HTTP 200 with `service` and `version` |
| `GET /livez` | HTTP 200 with `status: alive` |
| `GET /readyz` | HTTP 200 with `status: ready`, or HTTP 503 with `status: not_ready` |

Readiness becomes true when application startup completes and false during application cleanup. Liveness has no downstream dependencies. Invalid configuration prevents the server from starting rather than leaving a misconfigured process listening. `/backend` and browser documentation endpoints are not implemented.

## Configuration

| Environment variable | Default | Validation |
| --- | --- | --- |
| `SERVICE_NAME` | `platform-verification-api` | Nonempty, without control characters |
| `APP_PORT` | `8080` | Integer from 1 through 65535 |
| `ENVIRONMENT` | Required | Nonempty, without control characters |
| `RELEASE_VERSION` | Required | Nonempty, without control characters |
| `LOG_LEVEL` | `INFO` | DEBUG, INFO, WARNING, ERROR, or CRITICAL; case-insensitive |

Configuration is read at startup. Invalid settings produce a JSON error on standard error and exit code 2. Error messages identify the field without echoing its value. The release version comes from configuration, independently of the Python package version.

## Local execution

The implementation was tested with Python 3.14.6. Project metadata permits Python 3.12 and later, but those other runtimes have not been verified here. From this service directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
ENVIRONMENT=local RELEASE_VERSION=dev PYTHONPATH=src .venv/bin/python -m platform_verification_api
```

The server listens on `0.0.0.0:8080` by default. Runtime dependencies are pinned in `requirements.txt`; test-only dependencies are pinned in `requirements-test.txt`. The project also provides the `platform-verification-api` console entry point when installed as a Python package. The local commands above run directly from source.

## Logs and request IDs

Application and Uvicorn logs are JSON lines on standard output. Request logs include UTC timestamp, severity, service, environment, release, request ID, method, path, status, and duration in milliseconds. Lifecycle events identify application startup and cleanup.

An incoming `X-Request-ID` is accepted if it is a single header containing 1 to 64 ASCII letters, digits, dots, underscores, or hyphens, starting with a letter or digit. Missing, invalid, or duplicate IDs are replaced with a UUID. Responses and request logs carry the same ID.

Request bodies, query strings, and other headers are not logged. URL paths are logged, so secrets must not be placed in paths or request IDs. Unexpected application exceptions produce a generic HTTP 500 response; logs record the exception class without its message. Request logs use INFO for success, WARNING for client errors, and ERROR for server errors. Successful `/livez` and `/readyz` requests, which Kubernetes probes send every few seconds, use DEBUG. A not-ready `/readyz` response (HTTP 503) uses WARNING because it is an expected state rather than a server fault; an unexpected exception in that endpoint still uses ERROR. Higher configured log thresholds suppress lower-severity records, including successful requests and lifecycle events.

## Shutdown and container handoff

Uvicorn handles SIGTERM and SIGINT, stops accepting connections, and allows active requests to complete. The graceful-shutdown timeout is 20 seconds, leaving headroom within the architecture's 30-second Kubernetes termination period. Application cleanup clears readiness and records `application_stopped` after request draining.

The future container needs the runtime dependencies, source package, required environment variables, and the same server entry point. Signals must reach the Python server process. The application writes logs to standard output and has no runtime file-write requirement. Non-root and read-only-filesystem operation, container startup, and image vulnerability scanning remain container-packaging verification tasks.

## Verification

```sh
.venv/bin/python -m pytest
.venv/bin/python -m pip check
```

Tests cover service identity, readiness/liveness separation, configuration defaults and rejection, request-ID handling, JSON log fields, unsuccessful requests, sensitive-data exclusion, startup, and shutdown cleanup.

The POSIX process test starts the production server configuration with a test-only slow route, waits until a request is in flight, sends SIGTERM, and checks that the request completes and the server exits promptly. The slow route exists only in the test harness. A sandbox that denies localhost binding causes an explicit skip rather than a successful shutdown claim.

Initial verification: 39 tests passed and one process test was skipped because the sandbox denied local socket binding. Actual server startup and SIGTERM draining therefore remain unverified in this environment. Starlette also emits a deprecation warning for its HTTPX-backed test client; the current tests pass with the pinned dependencies.
