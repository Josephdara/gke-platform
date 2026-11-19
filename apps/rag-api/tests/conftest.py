import io
import json

import pytest

from rag_api.app import create_app
from rag_api.config import Settings
from rag_api.logging import create_logger
from rag_api.prompt import Passage

from fake_model import FakeModelServer


class StaticRetriever:
    def __init__(self, passages):
        self.passages = passages

    async def retrieve(self, question):
        return list(self.passages)

    async def health(self):
        return True


PASSAGES = [
    Passage("doc-1#0", "Probes", "A failing liveness probe restarts the container."),
    Passage("doc-2#0", "Deployments", "A Deployment replaces Pods during a rollout."),
]


@pytest.fixture
def settings():
    return Settings.from_env({"ENVIRONMENT": "test", "RELEASE_VERSION": "test-release", "MODEL_URL": "http://model"})


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
