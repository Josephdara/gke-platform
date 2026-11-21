# Platform Assistant frontend

This is the assistant's web interface: sign-in, conversations, streamed answers rendered as Markdown, and a compact list of each answer's sources that links to the original pages. It uses React 19, strict TypeScript, Vite, Tailwind CSS v4, and react-markdown with remark-gfm. rag-api serves the built files from `/`, so the page and its API share one origin and its session cookie.

There are two builds:

| Build | Command | API |
| --- | --- | --- |
| Real | `npm run build` | [`src/api/http.ts`](src/api/http.ts) talks to rag-api. The mock is not in the bundle |
| Mock | `npm run dev`, `npm run build:mock` | An in-memory mock with realistic delays and one scenario per state, for working on the interface without a backend |

The rag-api [Dockerfile](../Dockerfile) builds the real one in its first stage. To run it against the whole stack, see the [ingest README](../../ingest/README.md#running-it-locally) and [rag-api's README](../README.md#running-it-locally).

## Working on the interface

You need Node 26 LTS. From this directory:

```sh
npm ci
npm run dev
```

Sign in with `platform` / `platform-demo`, the mock's public demo account. The mock build shows "MOCK DATA" and "DEMO" badges; the real build shows neither.

## Mock scenarios

Add one `scenario` query parameter before signing in, for example `http://127.0.0.1:5173/?scenario=busy`. Use the port printed by the server. An unknown or absent scenario selects `default`. Reload to reset a scenario.

The ordinary stream waits about 3.4 seconds before its first text, then emits one token-sized piece about every 40 ms. The loading scenario waits about 7.8 seconds before its first text. API calls add small, abortable delays. Browser scheduling can extend these times. The mock handles liveness/readiness questions with probe fixtures and other questions with network-isolation fixtures; it is not a semantic search engine.

| Query value | What to do and expect |
| --- | --- |
| `default` | Sign in and ask a question for a streamed answer with sources. |
| `loading` | Observe workspace loading, then send a question for the longer thinking state. |
| `no-sources` | Send a question for a labelled general answer with no sources. |
| `unauthorized` | Send a question to expire the session and return to sign-in. |
| `rate-limited` | Send a question for a 429 with a five-second Retry-After countdown. |
| `busy` | Send a question for a 429 busy message with the same countdown. |
| `model-unavailable` | Observe the model status and send a question for a 503. |
| `retrieval-unavailable` | Observe the retrieval status and send a question for a 503. |
| `length` | Send a question for an answer cut off at its output limit. |
| `partial-failure` | Send a question for an upstream error after partial text. |
| `stream-failure` | Send a question for a stream error before any text. |
| `stream-model-unavailable` | Send a question for a model-unavailable event after partial text. |
| `deadline` | Send a question for a deadline error after partial text. |
| `stalled` | Send a question for a stalled-stream error after partial text. |
| `invalid-citations` | Complete an answer to see non-clickable unverified S9 and literal HTML-like text. |
| `sign-in-rate-limited` | Submit valid credentials for a five-second sign-in countdown. Enter the password again afterward. |
| `retrieval-mismatch` | See the index-mismatch status and a retrieval-unavailable response. |
| `retrieval-disabled` | See the disabled status and an answer with no retrieved sources. |
| `upstream-failed` | Send a question for an HTTP-level 503 upstream failure. |
| `question-empty` | Send a nonempty question to exercise the server's 422 empty-question response. |
| `question-too-long` | Send a valid-length question to exercise the server's 422 length response. |
| `conversation-not-found` | Open a saved conversation for its 404 state. |
| `unsafe-source` | Send a question to see sources with unsafe URLs shown without links. |
| `unauthorized-status` | Sign in to receive a 401 from status loading. |
| `unauthorized-list` | Sign in to receive a 401 from conversation-list loading. |
| `unauthorized-history` | Open a saved conversation to receive a 401. |
| `unauthorized-delete` | Confirm deletion of a conversation to receive a 401. |
| `unauthorized-signout` | Sign out to receive a 401 and return to sign-in. |

Busy and rate-limit scenarios allow the next explicitly submitted request once their countdown expires. No scenario sends a retry automatically. Other failure scenarios keep failing until you reload with another scenario. Stop is available both while thinking and while streaming. The mock retains stopped and failed partial answers in the current in-memory conversation.

## Checks

```sh
npm run lint
npm run typecheck
npm run build
npx playwright install chromium
npm run test:e2e
```

The 40 Playwright tests run in Chromium against a mock build served by `vite preview` on `127.0.0.1:4173`. They cover sign-in, streaming, sources and citations, stop, deletion, sign-out, every scenario above, explicit retry, keyboard focus, 360 px light and dark layouts, safe Markdown rendering of untrusted model output, and that the page makes no unexpected requests or CSP violations. Pull request validation runs lint, the type check, and the build in its `frontend-lint` step; Playwright runs locally.

## How it behaves

- Model output is untrusted. It is rendered as Markdown with react-markdown: raw HTML shows as text, images are dropped, and only http(s) links open, in a new tab. A citation such as `[S1]` links to its source only when rag-api validated it; an invalid one is marked "unverified". Saved answers that finished link the citations that name one of their saved sources.
- A stopped or failed answer keeps its partial text, marked "Stopped" or "Incomplete". Retry always asks first and never sends silently.
- A passage that is no longer in the corpus still shows the text saved with the answer.
- The session cookie is HttpOnly, so the page never reads it. The password is never stored. On load, the page asks `GET /api/session` whether you are already signed in.
- State-changing requests send `X-Assistant-Client: 1`, which rag-api requires with a matching Origin.

## File layout

```text
src/
  api/
    types.ts          Request, response, source, error, and SSE event payloads
    client.ts         AssistantApi interface, ApiError, mutation header contract
    fixtures.ts       Demo sources, answers, and seeded conversations
    mock.ts           In-memory API, scenario selection, abortable token streams
    http.ts           The real client: same-origin requests, the session cookie, streamed events
    index.ts          Chooses the mock or the real client at build time
  components/
    Answer.tsx        Answer mode label, status, copy/retry
    Dialog.tsx        Modal drawer/dialog focus and Escape handling
    Markdown.tsx      Safe Markdown, code blocks with copy, validated citation links
    Sidebar.tsx       Conversation navigation and deletion triggers
    SignIn.tsx        Uncontrolled credential form and sign-in cooldown
    Sources.tsx       One row per source document, linked to its section
  App.tsx             Session state and chat lifecycle
  hooks.ts            Wall-clock Retry-After countdown
  links.ts            Accepts only http(s) URLs for links
  main.tsx            API construction and React entry point
  styles.css          Tailwind theme tokens, responsive layouts, light/dark themes
tests/
  assistant.spec.ts   Chromium interaction and scenario coverage
```

The root also contains the Vite, TypeScript, ESLint, and Playwright configuration, package manifest, HTML entry point, local npm cache settings, and ignore rules. `node_modules/`, `dist/`, test outputs, reports, and caches are ignored.
