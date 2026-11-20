# ingest

ingest loads the assistant's corpus into pgvector. It reads the corpus manifest, checks every file's size and SHA-256, splits each changed Markdown document into chunks of about 300 tokens, embeds them through Text Embeddings Inference, and loads them. A rerun skips unchanged files, so you can run it as often as you like. In the cluster it runs as a suspended CronJob that you start by hand; on your machine it runs in the [Compose stack](../compose.yaml).

## What a run does

1. Reads `manifest.json` from the corpus source, either `gs://<bucket>/corpus/<revision>/` as its own Workload Identity, or a local directory.
2. Applies any new migration in [`migrations/`](migrations/). ingest owns the `rag` schema, so it is the only service that changes it.
3. Records the embedding model, revision, and dimensions the first time, and stops if the database already holds vectors from a different model.
4. Decides, for each document:

   | Decision | When | What happens |
   | --- | --- | --- |
   | new | The path is not in the database | Loaded |
   | changed | Its SHA-256 differs from the active revision, or it was retired and is back | The new revision's chunks are loaded and made active in one transaction, and the old chunks are deleted in the same transaction |
   | unchanged | Same SHA-256 | Skipped |
   | retired | The path is no longer in the manifest | Marked retired, and its chunks are deleted |

5. Parses each new or changed file within a size and time limit. Front matter, Hugo shortcodes, HTML comments, and tags are removed; fenced code is kept; each paragraph keeps the headings above it.
6. Chunks within a heading, never across one, using the embedding model's tokenizer, with about 40 tokens of overlap. Each chunk is embedded with its document title and heading path, so it matches the topic it sits under.
7. Writes a report with document, chunk, skip, and failure counts to the log and to `ingest_runs`, and, when `REPORT_BUCKET` is set, to `inference/ingest/<date>/` in the evidence bucket.

A file that fails its check, its parse, or its embedding fails alone: its previous revision stays active and the run carries on. Exit codes: `0` every file loaded or skipped, `1` a file failed or the run stopped, `2` configuration.

## Database roles

pgvector creates two roles on first start, from its [init script](../../platform/services/pgvector/init/10-roles.sh), and only it holds the superuser password.

| Role | Rights |
| --- | --- |
| `ingest` | Owns the `rag` schema: runs migrations and writes the corpus tables |
| `rag_api` | Reads `documents`, `chunks`, and `embedding_config`; reads and writes only `conversations` and `messages`. It cannot change the corpus or the schema |

## Configuration

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `ENVIRONMENT`, `RELEASE_VERSION` | Required | Recorded in the run |
| `CORPUS_SOURCE` | Required | `gs://<bucket>/corpus/<revision>/`, or a local directory |
| `EMBEDDINGS_URL` | Required | The Text Embeddings Inference server |
| `DATABASE_HOST`, `DATABASE_PASSWORD_FILE` | Required | pgvector's host, and the file holding the `ingest` role's password |
| `DATABASE_PORT`, `DATABASE_NAME`, `DATABASE_USER` | `5432`, `rag`, `ingest` | |
| `REPORT_BUCKET` | Unset | The evidence bucket for the run report |
| `CHUNK_TOKENS`, `OVERLAP_TOKENS` | `300`, `40` | Chunk size and overlap in model tokens |
| `EMBED_BATCH` | `16` | Chunks per embedding request, at most 32 |
| `MAX_FILE_BYTES`, `PARSE_SECONDS` | `2000000`, `10` | Limits for one file |

## Running it locally

You need Docker, the embedding model in `~/.cache/gke-platform-models` (from [`models/upload-model.sh`](../../models/upload-model.sh)), and a built corpus. From the repository root:

1. Create the three local database passwords, which stay in the ignored `apps/.local/`:

   ```sh
   mkdir -p apps/.local/pgvector
   for role in admin ingest rag-api; do python3 -c 'import secrets; print(secrets.token_urlsafe(24))' > "apps/.local/pgvector/$role"; done
   ```

2. Build a corpus snapshot from your working tree, for local use only:

   ```sh
   corpus/build_corpus.py --working-tree
   ```

   It prints the snapshot's directory, `corpus/build/<revision>`.

3. Start pgvector and the embeddings server, then run ingest against the snapshot:

   ```sh
   docker compose -f apps/compose.yaml up -d pgvector embeddings
   CORPUS_DIR="$PWD/corpus/build/<revision>" docker compose -f apps/compose.yaml run --rm ingest
   ```

   Run the last command again: every file is `unchanged`.

4. Stop the stack and delete its database when you are done:

   ```sh
   docker compose -f apps/compose.yaml down --volumes
   ```

## Testing

From `apps/ingest/`:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m pytest
.venv/bin/python -m pip check
```

35 tests pass for me, and 3 database tests are skipped. The tests use a fake embeddings server and an in-memory store. The database tests run migrations, reruns, revision switches, and retirements against a real pgvector, and check that `rag_api` cannot change the corpus or the schema and that `ingest` cannot manage roles. They empty the database's documents and conversations, so run them only against the local stack:

```sh
INGEST_TEST_DATABASE_URL="postgresql://ingest:$(cat ../.local/pgvector/ingest)@127.0.0.1:15432/rag" \
RAG_API_TEST_DATABASE_URL="postgresql://rag_api:$(cat ../.local/pgvector/rag-api)@127.0.0.1:15432/rag" \
.venv/bin/python -m pytest tests/test_database.py
```

Pull request validation runs the tests in the `test-ingest` step.
