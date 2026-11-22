import asyncio
import json
import os

import httpx
import pytest

from rag_api.app import create_app
from rag_api.logging import create_logger
from rag_api.prompt import GENERAL_PROMPT
from rag_api.retrieval import (
    EmbeddingConfigMismatch, PgCorpusStore, PgVectorRetriever, RetrievalUnavailable, TeiEmbeddings, clean_heading,
    section_url,
)

from conftest import parse_events, signed_in
from fake_model import FakeModelServer

EXPECTED = ("bge-small-en-v1.5", "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a", 384)
K8S = "https://kubernetes.io/docs/"
ROWS = [
    ("7-0123456789ab-0", "Probes", "Liveness", "A failing liveness probe restarts the container.", 0.82, K8S + "probes/"),
    ("7-0123456789ab-1", "Probes", "Readiness", "A failing readiness probe removes the Pod from endpoints.", 0.80, K8S + "probes/"),
    ("7-0123456789ab-2", "Probes", "Startup", "A startup probe delays the other probes.", 0.79, K8S + "probes/"),
    ("9-0123456789ab-2", "Deployments", "Rollouts", "A Deployment replaces Pods during a rollout.", 0.61, K8S + "deployment/"),
    ("3-0123456789ab-1", "Services", "", "A Service gives Pods a stable address.", 0.12, K8S + "service/"),
]
SOURCE = ("7-0123456789ab-0", "Probes", "Liveness", "A failing liveness probe restarts the container.",
          "https://kubernetes.io/docs/probes/", "CC BY 4.0", "The Kubernetes Authors")


class FakeStore:
    def __init__(self, config=EXPECTED, rows=ROWS):
        self.config, self.rows, self.limits, self.source_calls = config, rows, [], []

    async def embedding_config(self):
        return self.config

    async def search(self, vector, limit):
        assert len(vector) == 384
        self.limits.append(limit)
        return self.rows[:limit]

    async def source(self, chunk_id):
        self.source_calls.append(chunk_id)
        return SOURCE if chunk_id == SOURCE[0] else None


def embeddings(healthy=True, seen=None):
    def handle(request):
        if request.url.path == "/health":
            return httpx.Response(200 if healthy else 503)
        if not healthy:
            return httpx.Response(503)
        if seen is not None:
            seen.append(json.loads(request.content)["inputs"][0])
        return httpx.Response(200, json=[[0.01] * 384])
    return TeiEmbeddings(httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://tei"), 384)


def test_question_is_embedded_with_the_query_prefix_and_passages_are_capped_per_document(settings):
    seen, store = [], FakeStore()
    passages = asyncio.run(PgVectorRetriever(store, embeddings(seen=seen), settings).retrieve("Why restart?"))
    assert seen == ["Represent this sentence for searching relevant passages: Why restart?"]
    # Two passages per document at most, and none below the similarity floor.
    assert [p.chunk_id for p in passages] == ["7-0123456789ab-0", "7-0123456789ab-1", "9-0123456789ab-2"]
    assert passages[0].url == K8S + "probes/#liveness" and passages[0].score == 0.82
    assert store.limits == [15]


def test_a_weak_best_match_gets_no_passages_and_a_general_answer(settings):
    weak = [(*row[:4], 0.6, row[5]) for row in ROWS]
    model = FakeModelServer()
    app = create_app(settings, backend=model.backend(), retriever=PgVectorRetriever(FakeStore(rows=weak), embeddings(), settings))
    with signed_in(app) as client:
        meta = parse_events(client.post("/api/chat", json={"question": "ping"}).text)[0][1]
    assert (meta["mode"], meta["sources"]) == ("general", [])
    assert model.chat_bodies[0]["messages"][0]["content"] == GENERAL_PROMPT


def test_headings_are_cleaned_and_linked_to_their_section():
    explicit = "Disruptions > PodDisruptionBudget example {#pdb-example}"
    assert clean_heading(explicit) == "Disruptions > PodDisruptionBudget example"
    assert section_url(K8S + "disruptions/", explicit) == K8S + "disruptions/#pdb-example"
    assert section_url(K8S + "pods/", "Container states > `Terminated`") == K8S + "pods/#terminated"
    assert section_url("https://github.com/o/r/blob/abc/RUNBOOK.md", "Operate > Rotate a secret") == \
        "https://github.com/o/r/blob/abc/RUNBOOK.md#rotate-a-secret"
    assert section_url(K8S + "service/", "") == K8S + "service/"


def test_vectors_from_another_model_are_refused(settings):
    retriever = PgVectorRetriever(FakeStore(config=("other-model", "r", 384)), embeddings(), settings)
    with pytest.raises(EmbeddingConfigMismatch):
        asyncio.run(retriever.retrieve("Why?"))
    assert asyncio.run(retriever.status()) == "mismatch"


def test_embeddings_outage(settings):
    retriever = PgVectorRetriever(FakeStore(), embeddings(healthy=False), settings)
    with pytest.raises(RetrievalUnavailable):
        asyncio.run(retriever.retrieve("Why?"))
    assert asyncio.run(retriever.status()) == "unavailable"


def test_sources(settings):
    store = FakeStore()
    retriever = PgVectorRetriever(store, embeddings(), settings)
    assert asyncio.run(retriever.source("not-a-chunk-id")) is None
    assert store.source_calls == []
    app = create_app(settings, backend=FakeModelServer().backend(), retriever=retriever)
    with signed_in(app) as client:
        found = client.get("/api/sources/7-0123456789ab-0")
        missing = client.get("/api/sources/1-0123456789ab-9")
    assert found.status_code == 200
    assert found.json() == {"chunkId": SOURCE[0], "documentTitle": "Probes", "headingPath": "Liveness",
                            "text": SOURCE[3], "sourceUrl": SOURCE[4], "license": "CC BY 4.0",
                            "attribution": "The Kubernetes Authors"}
    assert missing.status_code == 404


def test_chat_uses_retrieved_passages(settings, log_stream):
    model = FakeModelServer()
    app = create_app(settings, create_logger(settings, log_stream), model.backend(),
                     PgVectorRetriever(FakeStore(), embeddings(), settings))
    with signed_in(app) as client:
        events = parse_events(client.post("/api/chat", json={"question": "Why restart?"}).text)
    meta = events[0][1]
    assert meta["mode"] == "documentation"
    assert [(s["label"], s["headingPath"], s["url"]) for s in meta["sources"]][0] == ("S1", "Liveness", K8S + "probes/#liveness")
    prompt = model.chat_bodies[0]["messages"][-1]["content"]
    assert "[S1] Probes > Liveness\nA failing liveness probe restarts the container." in prompt


def test_chat_refuses_when_retrieval_is_unavailable(settings):
    app = create_app(settings, backend=FakeModelServer().backend(),
                     retriever=PgVectorRetriever(FakeStore(), embeddings(healthy=False), settings))
    with signed_in(app) as client:
        response = client.post("/api/chat", json={"question": "Why?"})
        active = app.state.admission.active
    assert response.status_code == 503
    assert response.json() == {"detail": "retrieval_unavailable"}
    assert active == 0


DATABASE_URL = os.environ.get("RAG_API_TEST_DATABASE_URL")


@pytest.mark.skipif(not DATABASE_URL, reason="RAG_API_TEST_DATABASE_URL is not set")
def test_pgvector_store_against_a_loaded_database():
    """Run after ingest has loaded a corpus into the local Compose stack."""
    store = PgCorpusStore({"conninfo": DATABASE_URL})
    assert asyncio.run(store.embedding_config()) == EXPECTED
    rows = asyncio.run(store.search([0.05] * 384, 5))
    assert rows and len(rows) <= 5
    assert [row[4] for row in rows] == sorted((row[4] for row in rows), reverse=True)
    assert asyncio.run(store.source(rows[0][0]))[0] == rows[0][0]
