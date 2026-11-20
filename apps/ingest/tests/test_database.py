"""Migrations, loads, and the database roles against a real pgvector.

Skipped unless both variables point at a pgvector that the local Compose stack initialized, and
that the test may empty: INGEST_TEST_DATABASE_URL connects as ingest, RAG_API_TEST_DATABASE_URL
as rag_api. See the ingest README.
"""

import os

import psycopg
import pytest

from ingest.config import MIGRATIONS_DIR
from ingest.main import run
from ingest.source import LocalSource
from ingest.store import Store

from conftest import write_corpus
from fake_tei import FakeTei, vector

INGEST_URL = os.environ.get("INGEST_TEST_DATABASE_URL")
RAG_API_URL = os.environ.get("RAG_API_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not (INGEST_URL and RAG_API_URL), reason="test database URLs are not set")

A = "## Probes\n\nA failing liveness probe restarts the container.\n"
B = "## Services\n\nA Service gives Pods a stable address.\n"


@pytest.fixture
def ingest_db():
    with psycopg.connect(INGEST_URL, autocommit=True) as db:
        Store(db).migrate(MIGRATIONS_DIR)
        db.execute("DELETE FROM documents")
        db.execute("DELETE FROM conversations")
        yield db


def active_chunks(db):
    return db.execute("""SELECT d.path, count(*) FROM chunks c JOIN documents d ON d.id = c.document_id
                         WHERE c.revision = d.active_revision AND NOT d.retired GROUP BY d.path ORDER BY d.path""").fetchall()


def test_loads_reruns_changes_and_retirements(settings, tmp_path, ingest_db):
    corpus = tmp_path / "corpus"
    store = Store(ingest_db)
    write_corpus(corpus, {"a.md": A, "b.md": B})
    first = run(settings, LocalSource(str(corpus)), FakeTei().client(), store)
    assert (first["new"], first["chunksLoaded"]) == (2, 2)
    assert active_chunks(ingest_db) == [("a.md", 1), ("b.md", 1)]
    assert run(settings, LocalSource(str(corpus)), FakeTei().client(), store)["unchanged"] == 2

    write_corpus(corpus, {"a.md": A + "\nProbes can also run commands.\n"}, revision="rev-2")
    report = run(settings, LocalSource(str(corpus)), FakeTei().client(), store)
    assert (report["changed"], report["retired"]) == (1, 1)
    assert active_chunks(ingest_db) == [("a.md", 1)]
    # The previous revision's chunks are gone, not just hidden.
    assert ingest_db.execute("SELECT count(*) FROM chunks").fetchone()[0] == 1
    assert ingest_db.execute("SELECT status FROM ingest_runs ORDER BY id DESC LIMIT 1").fetchone()[0] == "succeeded"


def test_rag_api_reads_the_corpus_and_cannot_change_it(settings, tmp_path, ingest_db):
    write_corpus(tmp_path / "corpus", {"a.md": A})
    run(settings, LocalSource(str(tmp_path / "corpus")), FakeTei().client(), Store(ingest_db))
    with psycopg.connect(RAG_API_URL, autocommit=True) as rag:
        query = "[" + ",".join(str(v) for v in vector("liveness")) + "]"
        row = rag.execute("SELECT c.id, 1 - (c.embedding <=> %s::vector) FROM chunks c ORDER BY c.embedding <=> %s::vector LIMIT 1",
                          (query, query)).fetchone()
        assert row is not None
        rag.execute("INSERT INTO conversations (id, user_id, title) VALUES (gen_random_uuid(), 'u', 't')")
        for statement in ("UPDATE chunks SET text = 'changed'", "DELETE FROM documents",
                          "INSERT INTO embedding_config (id, model, revision, dimensions) VALUES (2, 'm', 'r', 1)",
                          "CREATE TABLE rag.extra (id int)", "DROP TABLE chunks"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                rag.execute(statement)


def test_ingest_cannot_manage_roles(ingest_db):
    for statement in ("CREATE ROLE intruder LOGIN", "ALTER ROLE rag_api SUPERUSER"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            ingest_db.execute(statement)
