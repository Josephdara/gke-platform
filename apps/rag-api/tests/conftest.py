from contextlib import contextmanager
import io
import json
from pathlib import Path
import tempfile

from fastapi.testclient import TestClient
import pytest

from rag_api.app import create_app
from rag_api.auth import hash_password
from rag_api.config import Settings
from rag_api.logging import create_logger
from rag_api.prompt import Passage

from fake_model import FakeModelServer


class StaticRetriever:
    def __init__(self, passages):
        self.passages = passages

    async def retrieve(self, question):
        return list(self.passages)

    async def source(self, chunk_id):
        return None

    async def status(self):
        return "ok"


PASSAGES = [
    Passage("doc-1#0", "Probes", "A failing liveness probe restarts the container."),
    Passage("doc-2#0", "Deployments", "A Deployment replaces Pods during a rollout."),
]


# Test-only accounts. Hashed once per run, because scrypt is deliberately slow.
PASSWORDS = {"tester": "correct horse battery", "other": "another long password", "benchmark": "benchmark password"}
AUTH_DIR = Path(tempfile.mkdtemp(prefix="rag-api-auth-"))
(AUTH_DIR / "users.json").write_text(json.dumps({"users": [
    {"username": name, "passwordHash": hash_password(password), "rateLimitExempt": name == "benchmark"}
    for name, password in PASSWORDS.items()]}))
(AUTH_DIR / "session-key").write_text("k" * 48)
ORIGIN = "http://testserver"
HEADERS = {"Origin": ORIGIN, "X-Assistant-Client": "1"}
AUTH_ENV = {"USERS_FILE": str(AUTH_DIR / "users.json"), "SESSION_KEY_FILE": str(AUTH_DIR / "session-key"),
            "ALLOWED_ORIGIN": ORIGIN, "COOKIE_SECURE": "false"}


@contextmanager
def signed_in(app, username="tester"):
    """A client that has signed in and sends the Origin and custom header on every request."""
    with TestClient(app, headers=HEADERS) as client:
        response = client.post("/api/session", json={"username": username, "password": PASSWORDS[username]})
        assert response.status_code == 204, response.text
        yield client


@pytest.fixture
def settings():
    return Settings.from_env({"ENVIRONMENT": "test", "RELEASE_VERSION": "test-release", "MODEL_URL": "http://model",
                              **AUTH_ENV})


@pytest.fixture
def log_stream():
    return io.StringIO()


@pytest.fixture
def model():
    return FakeModelServer()


@pytest.fixture
def make_app(settings, log_stream):
    def build(model, passages=PASSAGES, **overrides):
        configured = Settings(**{**settings.__dict__, **overrides})
        return create_app(configured, create_logger(configured, log_stream), model.backend(), StaticRetriever(passages))
    return build


def parse_events(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def terminal_events(events):
    return [event for event in events if event[0] in ("done", "error")]
