"""POST /api/chat: a bounded question in, a stream of server-sent events out."""

from collections.abc import AsyncIterator
import asyncio
import json
import time

import anyio
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from starlette.responses import JSONResponse, StreamingResponse

from .budget import Budget, BudgetExceeded, FittedPrompt, fit_prompt
from .inference import Finish, InferenceBackend, ModelUnavailable, Token, UpstreamError
from .metrics import (
    RAG_ACTIVE_STREAMS, RAG_COMPLETION, RAG_GENERATED_TOKENS, RAG_INVALID_CITATIONS, RAG_REJECTIONS,
    RAG_REQUESTS, RAG_RETRIEVAL, RAG_TTFT,
)
from .prompt import PROMPT_VERSION, check_citations

router = APIRouter()

# Seconds a refused caller is told to wait when every generation slot on this replica is busy.
ADMISSION_RETRY_SECONDS = 10


class Stalled(Exception):
    """No token arrived within the stall timeout."""


class DeadlineReached(Exception):
    """The request deadline passed before the stream finished."""


class ChatRequest(BaseModel):
    # Unknown fields, such as a client-chosen max_tokens, are rejected.
    model_config = ConfigDict(extra="forbid")
    question: str


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=True)}\n\n"


def rate_key(request: Request) -> str:
    # Until sign-in exists, the caller's address is the rate-limit key.
    return request.client.host if request.client else "unknown"


def refuse(reason: str, status: int, detail: str, retry_after: int | None = None) -> JSONResponse:
    RAG_REJECTIONS.labels(reason).inc()
    headers = {"Retry-After": str(retry_after)} if retry_after else None
    return JSONResponse({"detail": detail}, status_code=status, headers=headers)


@router.post("/api/chat")
async def chat(request: Request, body: ChatRequest):
    state = request.app.state
    settings = state.settings
    started = time.monotonic()
    question = body.question.strip()
    if not question:
        return JSONResponse({"detail": "question_empty"}, status_code=422)
    if len(question) > settings.max_input_chars:
        return refuse("input_too_long", 422, "question_too_long")
    wait = state.rate_limiter.check(rate_key(request))
    if wait:
        return refuse("rate_limit", 429, "rate_limited", wait)
    if not state.admission.try_acquire():
        return refuse("admission", 429, "busy", ADMISSION_RETRY_SECONDS)

    try:
        retrieval_started = time.monotonic()
        passages = await state.retriever.retrieve(question)
        RAG_RETRIEVAL.observe(time.monotonic() - retrieval_started)
        budget = Budget(settings.context_tokens, settings.output_tokens, settings.passage_tokens, settings.history_turns)
        fitted = await fit_prompt(question, [], passages, state.backend, budget)
    except BudgetExceeded:
        state.admission.release()
        return refuse("input_too_long", 422, "question_too_long")
    except UpstreamError as exc:
        state.admission.release()
        outcome = "model_unavailable" if isinstance(exc, ModelUnavailable) else "upstream_failed"
        RAG_REQUESTS.labels(outcome).inc()
        return JSONResponse({"detail": outcome}, status_code=503)
    except BaseException:
        state.admission.release()
        raise

    stream = stream_answer(state, fitted, request.state.request_id, started)
    return StreamingResponse(stream, media_type="text/event-stream", headers={"Cache-Control": "no-store"})


async def bounded(events: AsyncIterator, stall_seconds: float, deadline: float) -> AsyncIterator:
    """Yields upstream events, failing when one takes longer than the stall timeout or the deadline.

    Each wait gets its own timeout and nothing is yielded inside one, because a timeout spanning a
    yield would cancel whatever the consumer is awaiting instead of this stream.
    """
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DeadlineReached
            wait = min(stall_seconds, remaining)
            try:
                async with asyncio.timeout(wait):
                    event = await anext(events)
            except StopAsyncIteration:
                return
            except TimeoutError:
                raise (Stalled if wait == stall_seconds else DeadlineReached) from None
            yield event
    finally:
        # Closing the upstream request frees the model server's slot. The shield lets the close
        # finish even when the stream is being cancelled because the client went away.
        with anyio.CancelScope(shield=True):
            await events.aclose()


async def stream_answer(state, fitted: FittedPrompt, request_id: str, started: float) -> AsyncIterator[str]:
    settings = state.settings
    backend: InferenceBackend = state.backend
    outcome = "upstream_failed"
    parts: list[str] = []
    ttft: float | None = None
    finish: Finish | None = None
    citations = None
    deadline = started + settings.request_deadline_seconds
    guarded = bounded(backend.chat_stream(fitted.messages, settings.output_tokens), settings.stall_timeout_seconds, deadline)
    RAG_ACTIVE_STREAMS.inc()
    try:
        yield sse("meta", {
            "requestId": request_id,
            "promptVersion": PROMPT_VERSION,
            "model": backend.model_info().get("alias"),
            "sources": [
                {"label": f"S{n}", "chunkId": p.chunk_id, "title": p.title}
                for n, p in enumerate(fitted.passages, start=1)
            ],
        })
        try:
            async for event in guarded:
                if isinstance(event, Token):
                    if ttft is None:
                        ttft = time.monotonic() - started
                        RAG_TTFT.observe(ttft)
                    parts.append(event.text)
                    yield sse("token", {"text": event.text})
                elif isinstance(event, Finish):
                    finish = event
            # A stream that ends without a finish reason was cut short.
            if finish is not None:
                outcome = "length" if finish.reason == "length" else "complete"
        except DeadlineReached:
            outcome = "deadline"
        except Stalled:
            outcome = "stalled"
        except ModelUnavailable:
            outcome = "model_unavailable"
        except UpstreamError:
            outcome = "upstream_failed"
        except Exception as exc:
            outcome = "upstream_failed"
            state.logger.error("chat_stream_failed", extra={"request_id": request_id, "error_type": type(exc).__name__})

        if outcome in ("complete", "length"):
            citations = check_citations("".join(parts), len(fitted.passages))
            if citations.invalid:
                RAG_INVALID_CITATIONS.inc(len(citations.invalid))
            yield sse("done", {
                "status": outcome,
                "usage": {
                    "promptTokens": finish.prompt_tokens if finish.prompt_tokens is not None else fitted.prompt_tokens,
                    "completionTokens": finish.generated_tokens if finish.generated_tokens is not None else len(parts),
                },
                "timings": {
                    "ttftMs": round(ttft * 1000) if ttft is not None else None,
                    "totalMs": round((time.monotonic() - started) * 1000),
                },
                "citations": {"valid": citations.valid, "invalid": citations.invalid},
            })
        else:
            yield sse("error", {"reason": outcome, "partial": bool(parts)})
    except (asyncio.CancelledError, GeneratorExit):
        # The client went away, so there is nobody to send a terminal event to.
        outcome = "cancelled"
        raise
    finally:
        # Closes the upstream request when the client leaves mid-stream, too.
        with anyio.CancelScope(shield=True):
            await guarded.aclose()
        RAG_ACTIVE_STREAMS.dec()
        state.admission.release()
        generated = finish.generated_tokens if finish and finish.generated_tokens is not None else len(parts)
        RAG_GENERATED_TOKENS.inc(generated)
        RAG_REQUESTS.labels(outcome).inc()
        RAG_COMPLETION.observe(time.monotonic() - started)
        state.logger.info("chat_completed", extra={
            "request_id": request_id,
            "outcome": outcome,
            "ttft_ms": round(ttft * 1000) if ttft is not None else None,
            "prompt_tokens": fitted.prompt_tokens,
            "generated_tokens": generated,
            "passages": len(fitted.passages),
            "invalid_citations": len(citations.invalid) if citations else 0,
            "prompt_version": PROMPT_VERSION,
        })
