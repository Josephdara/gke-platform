"""Runs one ingest: verifies the corpus, loads changed documents, retires removed ones, reports.

Exit codes: 0 every file loaded or skipped, 1 a file failed or the run stopped, 2 configuration.
"""

from datetime import datetime, timezone
import json
import sys
import time

import httpx
import psycopg

from .chunk import chunk_sections
from .config import ConfigurationError, Settings
from .embed import EmbeddingError, TeiClient
from .manifest import ManifestError, parse_manifest
from .parse import ParseError, Section, parse_markdown
from .plan import plan
from .source import CorpusSource, SourceError, open_source, upload, verify
from .store import EmbeddingConfigMismatch, Store


def log(event: str, **fields) -> None:
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), "severity": fields.pop("severity", "INFO"),
              "service": "ingest", "event": event, **fields}
    print(json.dumps(record, ensure_ascii=True), flush=True)


def without_title(heading_path: str, title: str) -> str:
    """Drops a leading heading that repeats the document's title, which is shown beside it."""
    if heading_path == title:
        return ""
    return heading_path.removeprefix(f"{title} > ")


def run(settings: Settings, source: CorpusSource, tei: TeiClient, store: Store) -> dict:
    started = time.monotonic()
    manifest = parse_manifest(source.read("manifest.json"))
    migrations = store.migrate(settings.migrations_dir)
    store.ensure_embedding_config(settings.embedding_model, settings.embedding_revision, settings.embedding_dimensions)
    actions = plan(manifest.files, store.state())
    run_id = store.start_run(manifest.revision)
    counts = {"new": 0, "changed": 0, "unchanged": 0, "retired": 0, "failed": 0}
    failures, chunks_loaded = [], 0

    for action in actions:
        if action.kind == "unchanged":
            counts["unchanged"] += 1
            continue
        if action.kind == "retire":
            store.retire(action.path)
            counts["retired"] += 1
            log("document_retired", path=action.path)
            continue
        file = action.file
        try:
            data = verify(file, source.read(file.path), settings.max_file_bytes)
            sections = [Section(without_title(s.heading_path, file.title), s.paragraphs)
                        for s in parse_markdown(data, settings.parse_seconds)]
            chunks = chunk_sections(sections, tei.count, settings.chunk_tokens, settings.overlap_tokens)
            # The title and heading path are embedded with the text, so a chunk matches the
            # topic it sits under; only the text is stored and shown.
            vectors = tei.embed([f"{file.title}\n{c.heading_path}\n{c.text}" for c in chunks])
            chunks_loaded += store.load_revision(file, chunks, vectors)
            counts[action.kind] += 1
            log("document_loaded", path=file.path, kind=action.kind, chunks=len(chunks))
        except (SourceError, ParseError, EmbeddingError) as exc:
            # The document's previous revision, if any, stays active.
            counts["failed"] += 1
            failures.append({"path": file.path, "error": type(exc).__name__, "detail": str(exc)})
            log("document_failed", severity="ERROR", path=file.path, error=type(exc).__name__, detail=str(exc))

    report = {
        "run": run_id,
        "corpusRevision": manifest.revision,
        "documents": len(manifest.files),
        **counts,
        "chunksLoaded": chunks_loaded,
        "migrationsApplied": migrations,
        "failures": failures,
        "seconds": round(time.monotonic() - started, 2),
    }
    store.finish_run(run_id, "failed" if failures else "succeeded", report)
    return report


def main() -> None:
    try:
        settings = Settings.from_env()
        password = open(settings.database_password_file).read().strip()
    except ConfigurationError as exc:
        log("configuration_error", severity="ERROR", message=str(exc))
        raise SystemExit(2) from None
    except OSError as exc:
        log("configuration_error", severity="ERROR", message=f"DATABASE_PASSWORD_FILE could not be read: {type(exc).__name__}")
        raise SystemExit(2) from None

    with httpx.Client(timeout=httpx.Timeout(60, connect=5), trust_env=False) as client:
        try:
            with psycopg.connect(host=settings.database_host, port=settings.database_port, dbname=settings.database_name,
                                 user=settings.database_user, password=password, autocommit=True, connect_timeout=10) as db:
                report = run(settings, open_source(settings.corpus_source, client),
                             TeiClient(client, settings.embeddings_url, settings.embedding_dimensions, settings.embed_batch),
                             Store(db))
        except (ManifestError, SourceError, EmbeddingConfigMismatch, EmbeddingError, psycopg.Error) as exc:
            log("ingest_failed", severity="ERROR", error=type(exc).__name__, detail=str(exc).splitlines()[0] if str(exc) else "")
            raise SystemExit(1) from None

        log("ingest_finished", severity="ERROR" if report["failures"] else "INFO", report=report)
        if settings.report_bucket:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            name = f"{settings.report_prefix}{date}/run-{report['run']}-{report['corpusRevision']}.json"
            upload(client, settings.report_bucket, name, json.dumps(report, indent=2).encode())
            log("report_uploaded", bucket=settings.report_bucket, name=name)
    sys.exit(1 if report["failures"] else 0)
