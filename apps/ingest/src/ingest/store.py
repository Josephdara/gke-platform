"""The pgvector store: migrations, document state, and transactional loads."""

import json
from pathlib import Path

import psycopg

from .chunk import Chunk
from .manifest import CorpusFile
from .plan import DocumentState


class EmbeddingConfigMismatch(Exception):
    """The database holds vectors from a different embedding model."""


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.7g}" for value in vector) + "]"


class Store:
    def __init__(self, connection: psycopg.Connection):
        self.db = connection

    def migrate(self, directory: Path) -> list[str]:
        applied = []
        with self.db.transaction():
            self.db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        done = {row[0] for row in self.db.execute("SELECT version FROM schema_migrations")}
        for path in sorted(directory.glob("*.sql")):
            if path.stem in done:
                continue
            with self.db.transaction():
                self.db.execute(path.read_text())
                self.db.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,))
            applied.append(path.stem)
        return applied

    def ensure_embedding_config(self, model: str, revision: str, dimensions: int) -> None:
        with self.db.transaction():
            row = self.db.execute("SELECT model, revision, dimensions FROM embedding_config WHERE id = 1").fetchone()
            if row is None:
                self.db.execute("INSERT INTO embedding_config (id, model, revision, dimensions) VALUES (1, %s, %s, %s)",
                                (model, revision, dimensions))
            elif tuple(row) != (model, revision, dimensions):
                raise EmbeddingConfigMismatch

    def state(self) -> dict[str, DocumentState]:
        rows = self.db.execute("SELECT path, active_revision, retired FROM documents").fetchall()
        return {path: DocumentState(active, retired) for path, active, retired in rows}

    def start_run(self, corpus_revision: str) -> int:
        with self.db.transaction():
            return self.db.execute("INSERT INTO ingest_runs (corpus_revision, status) VALUES (%s, 'running') RETURNING id",
                                   (corpus_revision,)).fetchone()[0]

    def finish_run(self, run_id: int, status: str, report: dict) -> None:
        with self.db.transaction():
            self.db.execute("UPDATE ingest_runs SET finished_at = now(), status = %s, report = %s WHERE id = %s",
                            (status, json.dumps(report), run_id))

    def load_revision(self, file: CorpusFile, chunks: list[Chunk], vectors: list[list[float]]) -> int:
        """Loads a document's new revision and makes it the active one in a single transaction,
        so retrieval sees either the old chunks or the new ones, never a mix."""
        with self.db.transaction():
            document_id = self.db.execute(
                """INSERT INTO documents (path, title, source_url, license, attribution)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (path) DO UPDATE SET title = EXCLUDED.title, source_url = EXCLUDED.source_url,
                       license = EXCLUDED.license, attribution = EXCLUDED.attribution
                   RETURNING id""",
                (file.path, file.title, file.source, file.license, file.attribution)).fetchone()[0]
            self.db.execute("DELETE FROM chunks WHERE document_id = %s AND revision = %s", (document_id, file.sha256))
            with self.db.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO chunks (id, document_id, revision, ordinal, heading_path, text, token_count, embedding)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector)""",
                    [(f"{document_id}-{file.sha256[:12]}-{c.ordinal}", document_id, file.sha256, c.ordinal,
                      c.heading_path, c.text, c.token_count, vector_literal(v)) for c, v in zip(chunks, vectors)])
            self.db.execute("UPDATE documents SET active_revision = %s, retired = false, updated_at = now() WHERE id = %s",
                            (file.sha256, document_id))
            self.db.execute("DELETE FROM chunks WHERE document_id = %s AND revision <> %s", (document_id, file.sha256))
        return len(chunks)

    def retire(self, path: str) -> None:
        with self.db.transaction():
            row = self.db.execute("UPDATE documents SET retired = true, active_revision = NULL, updated_at = now() "
                                  "WHERE path = %s RETURNING id", (path,)).fetchone()
            if row:
                self.db.execute("DELETE FROM chunks WHERE document_id = %s", (row[0],))
