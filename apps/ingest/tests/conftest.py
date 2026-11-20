import hashlib
import json
from pathlib import Path

import pytest

from ingest.config import Settings
from ingest.plan import DocumentState


class FakeStore:
    """The Store interface in memory, for testing a run without a database."""

    def __init__(self):
        self.documents: dict[str, dict] = {}
        self.runs: list[dict] = []
        self.config = None

    def migrate(self, directory):
        return []

    def ensure_embedding_config(self, model, revision, dimensions):
        self.config = self.config or (model, revision, dimensions)

    def state(self):
        return {p: DocumentState(d["active"], d["retired"]) for p, d in self.documents.items()}

    def start_run(self, corpus_revision):
        self.runs.append({"revision": corpus_revision})
        return len(self.runs)

    def finish_run(self, run_id, status, report):
        self.runs[run_id - 1].update(status=status, report=report)

    def load_revision(self, file, chunks, vectors):
        assert len(chunks) == len(vectors)
        self.documents[file.path] = {"active": file.sha256, "retired": False, "chunks": list(chunks)}
        return len(chunks)

    def retire(self, path):
        self.documents[path].update(active=None, retired=True, chunks=[])


def write_corpus(root: Path, files: dict[str, str], revision="rev-1") -> None:
    """Writes files and a manifest that matches them."""
    root.mkdir(parents=True, exist_ok=True)
    entries = []
    for path, text in files.items():
        data = text.encode()
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(data)
        entries.append({"path": path, "title": path.split("/")[-1], "source": f"https://example.test/{path}",
                        "license": "CC BY 4.0", "attribution": "Example authors",
                        "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    (root / "manifest.json").write_text(json.dumps({"revision": revision, "files": entries}))


@pytest.fixture
def settings(tmp_path):
    return Settings.from_env({
        "ENVIRONMENT": "test", "RELEASE_VERSION": "test", "CORPUS_SOURCE": str(tmp_path / "corpus"),
        "EMBEDDINGS_URL": "http://tei", "DATABASE_HOST": "db", "DATABASE_PASSWORD_FILE": "/dev/null",
        "CHUNK_TOKENS": "60", "OVERLAP_TOKENS": "10",
    })
