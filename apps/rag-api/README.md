# rag-api

rag-api is the assistant's backend. It takes a question, builds a prompt that fits one model slot, streams the chat model's answer to you as server-sent events, and checks the answer's citations against the passages it sent. It talks to llama.cpp through llama.cpp's OpenAI-compatible routes, so the model server is a configuration value. With a database configured, it embeds each question, retrieves the five closest passages from pgvector, and can show any of them in full. Sign-in, conversation storage, and the frontend are not built yet. Without a database, every question gets no passages, and the model says the documentation provided does not answer it.

## Layout

| Module | Responsibility |
| --- | --- |
| `src/rag_api/chat.py` | `POST /api/chat`: limits, retrieval, the prompt budget, and the event stream |
| `src/rag_api/inference.py` | The inference adapter interface and its llama.cpp implementation |
| `src/rag_api/budget.py` | Fits the system prompt, history, passages, question, and reserved output into one slot |
| `src/rag_api/prompt.py` | The grounding prompt, its version, and the citation check |
| `src/rag_api/limits.py` | The per-replica admission limit and the rate limit |
| `src/rag_api/retrieval.py` | Retrieval: the question's embedding, the pgvector search as the read-only `rag_api` role, and the source lookup |
| `src/rag_api/routes.py` | Health, readiness, and status endpoints |
| `src/rag_api/config.py`, `logging.py`, `metrics.py`, `server.py`, `app.py` | Configuration, JSON logs, Prometheus metrics, and the server, carried over from the [verification API](../platform-verification-api/README.md) |
| `tests/` | Tests against a fake model server, plus a contract test against a real llama.cpp |

## HTTP interface

| Endpoint | Response |
| --- | --- |
| `POST /api/chat` | Body `{"question": "..."}`. Returns `text/event-stream`, or 422 for an empty or oversized question or any other field, 429 with `Retry-After` when the replica is busy or you are rate limited, and 503 when the model server or retrieval cannot be reached |
| `GET /healthz` | HTTP 200 while the process runs |
| `GET /readyz` | HTTP 200 once started, 503 during startup and shutdown. It never checks the model server, so a model outage does not take rag-api out of the load balancer |
| `GET /api/sources/{chunk_id}` | The exact passage, its document's title, heading path, source link, license, and attribution. 404 for an unknown chunk, a retired document, or a superseded revision |
| `GET /api/status` | The model server's health; retrieval's status (`ok`, `unavailable`, `mismatch` when the database holds vectors from another embedding model, or `disabled`); the prompt version; and how many generations are running |
| `GET /metrics` (metrics port) | Prometheus metrics |

A stream sends one `meta` event, then `token` events, then exactly one terminal event:

| Event | Data |
| --- | --- |
| `meta` | `requestId`, `promptVersion`, `model`, and `sources`, each with its label (`S1` to `S5`), `chunkId`, `title`, `headingPath`, and similarity `score` |
| `token` | `text`: the next piece of the answer |
| `done` | `status` (`complete`, or `length` when the 384-token limit cut the answer), `usage` (prompt and completion tokens), `timings` (`ttftMs`, `totalMs`), and `citations` (`valid` and `invalid` labels) |
| `error` | `reason` (`upstream_failed`, `stalled`, `deadline`, or `model_unavailable`) and `partial`, which is true when tokens were already sent |

If you disconnect, rag-api closes its request to the model server, which frees the model's slot, and sends nothing more.

## Configuration

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `ENVIRONMENT`, `RELEASE_VERSION` | Required | Recorded in every log line |
| `MODEL_URL` | Required | The model server's base URL, such as `http://staging-llm-cpu.staging-inference.svc.cluster.local:8080` |
| `MODEL_ALIAS` | `assistant-chat` | The model name the server answers to |
| `SERVICE_NAME`, `APP_PORT`, `METRICS_PORT`, `LOG_LEVEL` | `rag-api`, `8080`, `9090`, `INFO` | As in the verification API |
| `ADMISSION_LIMIT` | `3` | Generations one replica runs at once |
| `REQUEST_DEADLINE_SECONDS` | `120` | Longest a request may take, from arrival to the terminal event |
| `STALL_TIMEOUT_SECONDS` | `30` | Longest wait for the next token |
| `CONTEXT_TOKENS`, `OUTPUT_TOKENS` | `4096`, `384` | The model slot's size and the tokens reserved for the answer |
| `PASSAGE_TOKENS` | `1200` | Most tokens retrieved passages may use; the lowest-ranked are dropped first |
| `HISTORY_TURNS` | `2` | Most earlier question-and-answer turns kept in the prompt |
| `MAX_INPUT_CHARS` | `2000` | Longest question accepted |
| `RATE_LIMIT_PER_MINUTE` | `10` | Requests per minute per caller, counted on each replica |
| `DATABASE_HOST` | Unset | pgvector's host. Unset, retrieval is off |
| `DATABASE_PASSWORD_FILE`, `EMBEDDINGS_URL` | Required with a database | The `rag_api` role's password file, and the embeddings server |
| `DATABASE_PORT`, `DATABASE_NAME`, `DATABASE_USER` | `5432`, `rag`, `rag_api` | |
| `RETRIEVAL_TOP_K` | `5` | Passages retrieved, at most 5, because citations run from `[S1]` to `[S5]` |
| `SIMILARITY_FLOOR` | `0` | Passages below this cosine similarity are dropped; 0 keeps all of them until the evaluation tunes it |

Invalid settings stop the process with exit code 2 and a JSON error that names the field without echoing its value. `OUTPUT_TOKENS` plus `PASSAGE_TOKENS` must stay below `CONTEXT_TOKENS`, and the stall timeout below the deadline.

Logs never contain question or answer text. Each answer logs one `chat_completed` line with its request ID, outcome, time to first token, token counts, passage count, invalid citations, and prompt version.

## Running it locally

I run it against llama.cpp in Docker, using the same image digest and arguments as the cluster. Download the model first with [`models/upload-model.sh`](../../models/upload-model.sh), which keeps a verified copy in `~/.cache/gke-platform-models`. From the repository root:

```sh
docker run -d --name llm-local --user 10001:10001 --read-only --tmpfs /tmp \
  -v "$HOME/.cache/gke-platform-models/qwen2.5-1.5b-instruct-q4-k-m/91cad51170dc346986eccefdc2dd33a9da36ead9:/models:ro" \
  -p 127.0.0.1:18080:8080 \
  ghcr.io/ggml-org/llama.cpp@sha256:5b43086e3ba7ea5794d72904654f6cd41224a9b1c6ac0398f4940ee380d30f23 \
  --model /models/qwen2.5-1.5b-instruct-q4_k_m.gguf --host 0.0.0.0 --port 8080 --alias assistant-chat \
  --ctx-size 8192 --parallel 2 --n-predict 384 --threads 3 --metrics --no-slots --no-webui
```

Then, from `apps/rag-api/`:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
ENVIRONMENT=local RELEASE_VERSION=dev MODEL_URL=http://127.0.0.1:18080 PYTHONPATH=src .venv/bin/python -m rag_api
```

Ask a question and watch the events arrive:

```sh
curl -N http://127.0.0.1:8080/api/chat -H 'Content-Type: application/json' -d '{"question": "What does a liveness probe do?"}'
```

Remove the model server when you are done:

```sh
docker rm -f llm-local
```

## Testing

From `apps/rag-api/`:

```sh
.venv/bin/python -m pytest
.venv/bin/python -m pip check
```

66 tests pass for me, and 3 tests that need a real server or database are skipped. The tests use a fake model server that speaks llama.cpp's routes and stream format and can stream, fail mid-stream, stall, end without a finish reason, refuse, or be unreachable. Every stream test checks that the stream ends with exactly one terminal event and that the request to the model server was closed. The process test starts the real server and sends it SIGTERM during an answer; it is skipped where the environment does not allow binding a local socket.

The contract tests check the fake server's assumptions against a real llama.cpp: the stream format, that the template-aware token count equals the prompt size the server reports, and that closing a stream frees the server's slot. Run them with the local model server above whenever the llama.cpp image changes:

```sh
RAG_API_CONTRACT_URL=http://127.0.0.1:18080 .venv/bin/python -m pytest tests/test_contract.py
```

The pgvector store test runs against the local Compose stack after ingest has loaded a corpus, as the [ingest README](../ingest/README.md#running-it-locally) describes:

```sh
RAG_API_TEST_DATABASE_URL="postgresql://rag_api:$(cat ../.local/pgvector/rag-api)@127.0.0.1:15432/rag" .venv/bin/python -m pytest tests/test_retrieval.py
```

To ask questions against that corpus, run rag-api from source with `DATABASE_HOST=127.0.0.1`, `DATABASE_PORT=15432`, `DATABASE_PASSWORD_FILE=../.local/pgvector/rag-api`, and `EMBEDDINGS_URL=http://127.0.0.1:18090`, and start the chat model with `docker compose -f apps/compose.yaml --profile chat up -d llm`.

Pull request validation runs the tests in the `test-rag-api` step; see the [pipeline README](../../pipeline/README.md#what-a-build-does).
