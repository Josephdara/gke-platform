# Platform Verification API

I use this small Python HTTP API to verify the platform's deployment, health, configuration, and logging behavior. FastAPI handles requests and Uvicorn manages the server lifecycle. The Dockerfile in this directory builds the image. To test the service and build its image, see the [applications README](../README.md); to scan and deploy it, see the [platform README](../../platform/README.md).

## Layout

| Module | Responsibility |
| --- | --- |
| `src/platform_verification_api/app.py` | Application factory, startup, and shutdown |
| `src/platform_verification_api/routes.py` | Service identity and health endpoints |
| `src/platform_verification_api/config.py` | Environment configuration and validation |
| `src/platform_verification_api/secret.py` | Mounted secret validation and reload |
| `src/platform_verification_api/logging.py` | JSON logs and request IDs |
| `src/platform_verification_api/metrics.py` | Prometheus request metrics |
| `src/platform_verification_api/server.py` | Uvicorn configuration and entry point |
| `tests/` | Configuration, endpoint, logging, metrics, lifecycle, and process tests |

## HTTP interface

| Endpoint | Response |
| --- | --- |
| `GET /` | HTTP 200 with `service` and `version`, plus `secretLabel` when `SECRET_FILE` is set |
| `GET /livez` | HTTP 200 with `status: alive` |
| `GET /readyz` | HTTP 200 with `status: ready`, or HTTP 503 with `status: not_ready` |

Readiness becomes true when application startup completes and false during application cleanup. Liveness has no downstream dependencies. Invalid configuration stops the server from starting, so a misconfigured process never listens. `/backend` and browser documentation endpoints are not implemented. With `SECRET_FILE` set, readiness also requires a valid secret.

## Configuration

| Environment variable | Default | Validation |
| --- | --- | --- |
| `SERVICE_NAME` | `platform-verification-api` | Nonempty, without control characters |
| `APP_PORT` | `8080` | Integer from 1 through 65535 |
| `METRICS_PORT` | `9090` | Integer from 1 through 65535, different from `APP_PORT` |
| `ENVIRONMENT` | Required | Nonempty, without control characters |
| `RELEASE_VERSION` | Required | Nonempty, without control characters |
| `LOG_LEVEL` | `INFO` | DEBUG, INFO, WARNING, ERROR, or CRITICAL; case-insensitive |
| `SECRET_FILE` | Unset | Optional path to a mounted JSON secret; nonempty, without control characters |

The service reads configuration at startup. Invalid settings produce a JSON error on standard error and exit code 2. Error messages name the field without echoing its value. The release version comes from configuration, independently of the Python package version.

## Mounted secret

When `SECRET_FILE` is set, the service reads a JSON object with a `label` and a nonempty `value` from that file. The label must be 1 to 63 ASCII letters, digits, dots, underscores, or hyphens, starting with a letter or digit, because `/` returns it. The value stays internal and is never logged or returned.

Every `/` and `/readyz` request rereads the file and acts only when its content changes, so a rotated version takes effect without a restart. A valid change logs `secret_loaded` with the label. Until a valid secret loads, `/readyz` returns HTTP 503 and `secret_load_failed` is logged. After that, an invalid change keeps the last valid label and logs `secret_reload_failed`. Failure logs carry only the exception class, once per change.

## Running from source

The image and the pipeline's tests use Python 3.14.8. The project metadata allows Python 3.12 and later, but I have not verified other versions. After you create the virtual environment as described in [Testing the Python service](../README.md#testing-the-python-service), run from this directory:

```sh
ENVIRONMENT=local RELEASE_VERSION=dev PYTHONPATH=src .venv/bin/python -m platform_verification_api
```

The server listens on `0.0.0.0:8080` by default and serves metrics on port 9090. Runtime dependencies are pinned in `requirements.txt` and test-only dependencies in `requirements-test.txt`. When installed as a Python package, the project also provides the `platform-verification-api` console entry point.

## Logs and request IDs

Application and Uvicorn logs are JSON lines on standard output. Request logs include UTC timestamp, severity, service, environment, release, request ID, method, path, status, and duration in milliseconds. Lifecycle events mark application startup and cleanup.

An incoming `X-Request-ID` is accepted if it is a single header containing 1 to 64 ASCII letters, digits, dots, underscores, or hyphens, starting with a letter or digit. Missing, invalid, or duplicate IDs are replaced with a UUID. Responses and request logs carry the same ID.

Request bodies, query strings, and other headers are not logged. URL paths are logged, so never put secrets in paths or request IDs. An unexpected exception produces a generic HTTP 500 response, and the log records the exception class without its message.

Request logs use INFO for success, WARNING for client errors, and ERROR for server errors. Successful `/livez` and `/readyz` requests, which Kubernetes probes send every few seconds, use DEBUG. A not-ready `/readyz` response (HTTP 503) uses WARNING because it is an expected state, not a server fault; an unexpected exception in that endpoint still uses ERROR. A higher `LOG_LEVEL` suppresses lower-severity records, including successful requests and lifecycle events.

## Metrics

The service serves Prometheus metrics at `/metrics` on `METRICS_PORT`, separate from the application port, so routing the application port to the internet does not expose them.

| Metric | Labels | Content |
| --- | --- | --- |
| `http_requests_total` | `method`, `route`, `status` | Requests handled |
| `http_request_duration_seconds` | `method`, `route` | Histogram of the time from receiving a request to finishing its response |

`route` is the matched route template, or `unmatched`, and `method` is a standard HTTP method or `other`, so unexpected paths and methods cannot create new series. Errors are the requests with a 5xx `status`. `/livez` and `/readyz` are not counted, because Kubernetes probes would dominate the counts and a not-ready response is not a server error. The client library also exports its default process and Python runtime metrics.

## Shutdown and container runtime

Uvicorn handles SIGTERM and SIGINT, stops accepting connections, and lets active requests complete. The graceful-shutdown timeout is 20 seconds, leaving headroom within the chart's 30-second termination period. Application cleanup clears readiness and logs `application_stopped` after requests drain. After Ctrl+C, the process exits with status 130 without a traceback.

The container runs the server entry point in exec form, so signals reach the Python process directly. The application writes logs to standard output and needs no writable filesystem. It runs as user `10001` with a read-only root filesystem, no capabilities, and no privilege escalation; I verified this in Docker and on Docker Desktop Kubernetes. pip is removed from the runtime image after dependencies are installed, and the image passes the Trivy gate for fixable HIGH and CRITICAL vulnerabilities.

## Tests

Run the tests as described in [Testing the Python service](../README.md#testing-the-python-service). They cover service identity, readiness and liveness separation, configuration defaults and rejection, request-ID handling, JSON log fields, request metrics and their label bounds, unsuccessful requests, sensitive-data exclusion, mounted secret loading, rotation, and failure handling, startup, and shutdown cleanup.

The process test starts the production server configuration with a test-only slow route, waits until a request is in flight, sends SIGTERM, and checks that the request completes and the server exits promptly. If the environment denies binding a local socket, the test is skipped rather than reported as passing. Starlette emits a deprecation warning for its HTTPX-backed test client; the tests pass with the pinned dependencies.
