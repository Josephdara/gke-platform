"""Prometheus request metrics with bounded label values."""

from prometheus_client import Counter, Histogram, disable_created_metrics
from starlette.types import Scope

METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})

disable_created_metrics()
REQUESTS = Counter("http_requests", "HTTP requests handled, excluding health probes.", ["method", "route", "status"])
DURATION = Histogram("http_request_duration_seconds", "HTTP request duration, excluding health probes.", ["method", "route"])


def record_request(scope: Scope, status: int, seconds: float) -> None:
    method = scope["method"] if scope["method"] in METHODS else "other"
    route = getattr(scope.get("route"), "path", "unmatched")
    REQUESTS.labels(method, route, str(status)).inc()
    DURATION.labels(method, route).observe(seconds)
