"""Retrieval: embed the question, search pgvector, return passages best first."""

from dataclasses import dataclass
import re
from typing import Protocol

import httpx
import psycopg

from .prompt import Passage

CHUNK_ID = re.compile(r"[0-9]{1,18}-[0-9a-f]{12}-[0-9]{1,6}\Z")


class RetrievalUnavailable(Exception):
    """The database or the embeddings server failed."""


class EmbeddingConfigMismatch(RetrievalUnavailable):
    """The database holds vectors from another embedding model, which would compare as noise."""


@dataclass(frozen=True)
class Source:
    chunk_id: str
    document_title: str
    heading_path: str
    text: str
    source_url: str
    license: str
    attribution: str


class Retriever(Protocol):
    async def retrieve(self, question: str) -> list[Passage]: ...

    async def source(self, chunk_id: str) -> Source | None: ...

    async def status(self) -> str: ...


class NoRetriever:
    """Used when no database is configured: every question gets no passages."""

    async def retrieve(self, question: str) -> list[Passage]:
        return []

    async def source(self, chunk_id: str) -> Source | None:
        return None

    async def status(self) -> str:
        return "disabled"


class CorpusStore(Protocol):
    async def embedding_config(self) -> tuple[str, str, int] | None: ...

    async def search(self, vector: list[float], limit: int) -> list[tuple]: ...

    async def source(self, chunk_id: str) -> tuple | None: ...


# Only chunks of each document's active revision, and never a retired document.
SEARCH = """
SELECT c.id, d.title, c.heading_path, c.text, 1 - (c.embedding <=> %(v)s::vector) AS score
FROM chunks c JOIN documents d ON d.id = c.document_id
WHERE NOT d.retired AND c.revision = d.active_revision
ORDER BY c.embedding <=> %(v)s::vector
LIMIT %(limit)s
"""
SOURCE = """
SELECT c.id, d.title, c.heading_path, c.text, d.source_url, d.license, d.attribution
FROM chunks c JOIN documents d ON d.id = c.document_id
WHERE c.id = %s AND NOT d.retired AND c.revision = d.active_revision
"""


class PgCorpusStore:
    """Reads the corpus as rag_api, which may only select from it. One connection per call:
    a call costs milliseconds against an answer of many seconds, and nothing is pooled."""

    def __init__(self, conninfo: dict):
        self.conninfo = conninfo

    async def _query(self, sql: str, params, one: bool):
        try:
            async with await psycopg.AsyncConnection.connect(**self.conninfo, autocommit=True, connect_timeout=5) as db:
                cursor = await db.execute(sql, params)
                return await (cursor.fetchone() if one else cursor.fetchall())
        except psycopg.Error as exc:
            raise RetrievalUnavailable(type(exc).__name__) from None

    async def embedding_config(self):
        row = await self._query("SELECT model, revision, dimensions FROM embedding_config WHERE id = 1", (), True)
        return tuple(row) if row else None

    async def search(self, vector, limit):
        literal = "[" + ",".join(f"{v:.7g}" for v in vector) + "]"
        return await self._query(SEARCH, {"v": literal, "limit": limit}, False)

    async def source(self, chunk_id):
        return await self._query(SOURCE, (chunk_id,), True)


class TeiEmbeddings:
    def __init__(self, client: httpx.AsyncClient, dimensions: int):
        self.client = client
        self.dimensions = dimensions

    async def embed(self, text: str) -> list[float]:
        try:
            response = await self.client.post("/embed", json={"inputs": [text], "truncate": True, "normalize": True})
        except httpx.HTTPError as exc:
            raise RetrievalUnavailable(type(exc).__name__) from None
        if response.status_code != 200:
            raise RetrievalUnavailable(f"/embed returned HTTP {response.status_code}")
        vectors = response.json()
        if not isinstance(vectors, list) or len(vectors) != 1 or len(vectors[0]) != self.dimensions:
            raise RetrievalUnavailable("/embed returned an unexpected vector")
        return vectors[0]

    async def health(self) -> bool:
        try:
            return (await self.client.get("/health")).status_code == 200
        except httpx.HTTPError:
            return False


class PgVectorRetriever:
    def __init__(self, store: CorpusStore, embeddings: TeiEmbeddings, settings):
        self.store = store
        self.embeddings = embeddings
        self.settings = settings
        self.expected = (settings.embedding_model, settings.embedding_revision, settings.embedding_dimensions)
        self.config_checked = False

    async def _check_config(self) -> None:
        if not self.config_checked:
            if await self.store.embedding_config() != self.expected:
                raise EmbeddingConfigMismatch
            self.config_checked = True

    async def retrieve(self, question: str) -> list[Passage]:
        await self._check_config()
        vector = await self.embeddings.embed(self.settings.query_prefix + question)
        rows = await self.store.search(vector, self.settings.retrieval_top_k)
        return [Passage(chunk_id, title, text, float(score), heading)
                for chunk_id, title, heading, text, score in rows if score >= self.settings.similarity_floor]

    async def source(self, chunk_id: str) -> Source | None:
        if not CHUNK_ID.fullmatch(chunk_id):
            return None
        row = await self.store.source(chunk_id)
        return Source(*row) if row else None

    async def status(self) -> str:
        try:
            if not await self.embeddings.health():
                return "unavailable"
            self.config_checked = False
            await self._check_config()
        except EmbeddingConfigMismatch:
            return "mismatch"
        except RetrievalUnavailable:
            return "unavailable"
        return "ok"
