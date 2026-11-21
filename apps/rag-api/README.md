# rag-api

rag-api is the assistant's backend. It takes a question, builds a prompt that fits one model slot, streams the chat model's answer to you as server-sent events, and checks the answer's citations against the passages it sent. It talks to llama.cpp through llama.cpp's OpenAI-compatible routes, so the model server is a configuration value. With a database configured, it embeds each question, retrieves the five closest passages from pgvector, can show any of them in full, and saves each conversation for its signed-in user. It also serves the [frontend](frontend/README.md) from `/`. Without a database, every question gets a general answer and conversations last until the process restarts.

## Layout

| Module | Responsibility |
| --- | --- |
| `src/rag_api/chat.py` | `POST /api/chat`: limits, retrieval, the prompt budget, and the event stream |
| `src/rag_api/inference.py` | The inference adapter interface and its llama.cpp implementation |
| `src/rag_api/budget.py` | Fits the system prompt, history, passages, question, and reserved output into one slot |
| `src/rag_api/prompt.py` | The documentation and general prompts, their version, and the citation check |
| `src/rag_api/limits.py` | The per-replica admission limit and the rate limit |
| `src/rag_api/retrieval.py` | Retrieval: the question's embedding, the pgvector search as the read-only `rag_api` role, and the source lookup |
| `src/rag_api/routes.py` | Sign-in, conversations, sources, health, readiness, and status endpoints |
| `src/rag_api/auth.py` | Accounts, signed session cookies, the Origin and custom-header check |
| `src/rag_api/passwords.py` | scrypt password hashes, with only the standard library, so `tools/make_users.py` runs with any recent `python3` |
| `src/rag_api/conversations.py` | Conversation storage, scoped to the signed-in user, in pgvector or in memory |
| `src/rag_api/web.py` | The built frontend, and the security headers on every response |
| `frontend/` | The web interface; see its [README](frontend/README.md) |
| `tools/make_users.py` | Prompts for accounts and prints the users file, for piping into Secret Manager |
| `src/rag_api/config.py`, `logging.py`, `metrics.py`, `server.py`, `app.py` | Configuration, JSON logs, Prometheus metrics, and the server, carried over from the [verification API](../platform-verification-api/README.md) |
| `tests/` | Tests against a fake model server, plus a contract test against a real llama.cpp |

## HTTP interface

| Endpoint | Response |
| --- | --- |
| `GET /api/session`, `POST /api/session`, `DELETE /api/session` | Who is signed in (401 if nobody); sign in with `{"username", "password"}` (204 and the cookie, 401 `invalid_credentials`, 429 after 5 attempts a minute per address or username); sign out (204) |
| `GET /api/conversations`, `GET` and `DELETE /api/conversations/{id}` | The signed-in user's conversations, newest first; one with its messages, each with its status (`complete`, `length`, `cancelled`, `failed`) and sources including their text; delete one. Another user's conversation is a 404 |
| `POST /api/chat` | Body `{"question": "...", "conversationId": "..."}`, where the conversation is optional; history comes from it, never from the client. Returns `text/event-stream`, or 422 for an empty or oversized question or any other field, 429 with `Retry-After` when the replica is busy or you are rate limited, and 503 when the model server or retrieval cannot be reached |
| `GET /healthz` | HTTP 200 while the process runs |
| `GET /readyz` | HTTP 200 once started, 503 during startup and shutdown. It never checks the model server, so a model outage does not take rag-api out of the load balancer |
| `GET /api/sources/{chunk_id}` | The exact passage, its document's title, heading path, source link, license, and attribution. 404 for an unknown chunk, a retired document, or a superseded revision |
| `GET /api/status` | The model server's health; retrieval's status (`ok`, `unavailable`, `mismatch` when the database holds vectors from another embedding model, or `disabled`); the prompt version; and how many generations are running |
| `GET /metrics` (metrics port) | Prometheus metrics |
| Any other path | The frontend, with `index.html` for page routes, when `STATIC_DIR` is set |

Every `/api/` route except signing in needs the session cookie: an HMAC-signed username and expiry, `HttpOnly`, `SameSite=Strict`, `Secure`, valid for 8 hours. Any replica can check it, and rotating the session key signs everyone out. State-changing requests also need an `Origin` equal to `ALLOWED_ORIGIN` and the header `X-Assistant-Client: 1`, or they get 403. Every response carries a Content Security Policy that allows only the site's own scripts, styles, and API.

A stream sends one `meta` event, then `token` events, then exactly one terminal event:

| Event | Data |
| --- | --- |
| `meta` | `requestId`, `conversationId`, `promptVersion`, `model`, `mode` (`documentation`, or `general` when no passage was relevant), and `sources`, each with its label (`S1` to `S5`), `chunkId`, `title`, `headingPath`, `url` (the source page at the passage's section), and similarity `score` |
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
| `RATE_LIMIT_PER_MINUTE` | `10` | Questions per minute per user, counted on each replica; an account marked `rateLimitExempt` skips it |
| `USERS_FILE`, `SESSION_KEY_FILE` | Required | The users file, `{"users": [{"username", "passwordHash", "rateLimitExempt"}]}`, and a key of at least 32 bytes |
| `ALLOWED_ORIGIN` | Required | The site's origin, such as `https://assistant.staging.gke.josephdara.com` |
| `COOKIE_SECURE` | `true` | `false` only for a local `http://` origin |
| `SESSION_HOURS`, `LOGIN_ATTEMPTS_PER_MINUTE` | `8`, `5` | |
| `FORWARDED_HOPS` | `0` | `X-Forwarded-For` entries the load balancer adds; 2 behind GKE's external Application Load Balancer, so sign-in throttling sees the real client |
| `STATIC_DIR` | Unset; `/app/static` in the image | The built frontend |
| `DATABASE_HOST` | Unset | pgvector's host. Unset, retrieval is off |
| `DATABASE_PASSWORD_FILE`, `EMBEDDINGS_URL` | Required with a database | The `rag_api` role's password file, and the embeddings server |
| `DATABASE_PORT`, `DATABASE_NAME`, `DATABASE_USER` | `5432`, `rag`, `rag_api` | |
| `RETRIEVAL_TOP_K` | `5` | Passages retrieved, at most 5, because citations run from `[S1]` to `[S5]` |
| `RELEVANCE_FLOOR` | `0.65` | When the best passage scores below this, the question gets no passages and a general answer |
| `SIMILARITY_FLOOR` | `0.60` | A single passage below this cosine similarity is dropped |

Invalid settings stop the process with exit code 2 and a JSON error that names the field without echoing its value. `OUTPUT_TOKENS` plus `PASSAGE_TOKENS` must stay below `CONTEXT_TOKENS`, and the stall timeout below the deadline.

Logs never contain question or answer text. Each answer logs one `chat_completed` line with its request ID, outcome, time to first token, token counts, passage count, invalid citations, and prompt version.

## Running it locally

The [Compose stack](../compose.yaml) runs everything: pgvector, the embeddings server, the chat model, and rag-api built from its Dockerfile, with the frontend at `http://127.0.0.1:8080`. You need the models in `~/.cache/gke-platform-models` (from [`models/upload-model.sh`](../../models/upload-model.sh)), the local database passwords and a loaded corpus, as the [ingest README](../ingest/README.md#running-it-locally) describes, and a local account. From the repository root:

```sh
mkdir -p apps/.local/rag-api
python3 -c 'import secrets; print(secrets.token_urlsafe(48), end="")' > apps/.local/rag-api/session-key
apps/rag-api/tools/make_users.py > apps/.local/rag-api/users.json
docker compose -f apps/compose.yaml --profile chat --profile app up -d --build
```

Open `http://127.0.0.1:8080`, using `127.0.0.1` rather than `localhost`, because sign-in requires the exact origin. Stop everything with:

```sh
docker compose -f apps/compose.yaml --profile chat --profile app down
```

## Testing

From `apps/rag-api/`:

```sh
.venv/bin/python -m pytest
.venv/bin/python -m pip check
```

85 tests pass for me, and 4 tests that need a real server or database are skipped. The tests use a fake model server that speaks llama.cpp's routes and stream format and can stream, fail mid-stream, stall, end without a finish reason, refuse, or be unreachable. Every stream test checks that the stream ends with exactly one terminal event and that the request to the model server was closed. The process test starts the real server and sends it SIGTERM during an answer; it is skipped where the environment does not allow binding a local socket.

The contract tests check the fake server's assumptions against a real llama.cpp: the stream format, that the template-aware token count equals the prompt size the server reports, and that closing a stream frees the server's slot. Run them with the local model server above whenever the llama.cpp image changes:

```sh
RAG_API_CONTRACT_URL=http://127.0.0.1:18080 .venv/bin/python -m pytest tests/test_contract.py
```

The pgvector store tests, for retrieval and conversations, run against the local Compose stack after ingest has loaded a corpus:

```sh
RAG_API_TEST_DATABASE_URL="postgresql://rag_api:$(cat ../.local/pgvector/rag-api)@127.0.0.1:15432/rag" .venv/bin/python -m pytest tests/test_retrieval.py tests/test_conversations.py
```

Pull request validation runs the tests in the `test-rag-api` step; see the [pipeline README](../../pipeline/README.md#what-a-build-does).
