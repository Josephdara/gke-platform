"""POST /api/chat: a bounded question in, a stream of server-sent events out."""

from collections.abc import AsyncIterator
import asyncio
import json
import time

import anyio
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from starlette.responses import JSONResponse, StreamingResponse

from .auth import current_user, forbidden_mutation, unauthorized
from .budget import Budget, BudgetExceeded, FittedPrompt, fit_prompt
from .conversations import ConversationsUnavailable, StoredMessage, history, valid_id
from .inference import Finish, InferenceBackend, ModelUnavailable, Token, UpstreamError
from .guardrails import Verdict
from .metrics import (
    RAG_ACTIVE_STREAMS, RAG_COMPLETION, RAG_GENERATED_TOKENS, RAG_GUARDRAIL_CHECKS, RAG_GUARDRAIL_SECONDS,
    RAG_INVALID_CITATIONS, RAG_REJECTIONS, RAG_REQUESTS, RAG_RETRIEVAL, RAG_TTFT,
)
from .prompt import PROMPT_VERSION, check_citations
from .retrieval import RetrievalUnavailable

router = APIRouter()

# Seconds a refused caller is told to wait when every generation slot on this replica is busy.
ADMISSION_RETRY_SECONDS = 10


class Stalled(Exception):
    """No token arrived within the stall timeout."""


class DeadlineReached(Exception):
    """The request deadline passed before the stream finished."""


class ChatRequest(BaseModel):
    # Unknown fields, such as a client-chosen max_tokens, are rejected. History comes only from
    # the stored conversation, never from the client.
    model_config = ConfigDict(extra="forbid")
    question: str
    conversationId: str | None = None


# What is saved, and shown, in place of an answer Model Armor flagged in block mode.
WITHHELD = "This answer was withheld because it did not pass the content policy."

# How each stream outcome is saved on the answer.
SAVED_STATUS = {"complete": "complete", "length": "length", "cancelled": "cancelled"}


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=True)}\n\n"


def refuse(reason: str, status: int, detail: str, retry_after: int | None = None) -> JSONResponse:
    RAG_REJECTIONS.labels(reason).inc()
    headers = {"Retry-After": str(retry_after)} if retry_after else None
    return JSONResponse({"detail": detail}, status_code=status, headers=headers)


async def screen(state, point: str, text: str, request_id: str) -> Verdict:
    """Runs one Model Armor check and records its result. Only filter names are logged."""
    started = time.monotonic()
    guardrail = state.guardrail
    verdict = await (guardrail.screen_response(text) if point == "answer" else guardrail.screen_prompt(text))
    if state.settings.model_armor_mode != "off":
        RAG_GUARDRAIL_SECONDS.labels(point).observe(time.monotonic() - started)
        result = "flagged" if verdict.flagged else "clear" if verdict.checked else "unavailable"
        RAG_GUARDRAIL_CHECKS.labels(point, result).inc()
        if verdict.flagged:
            state.logger.warning("guardrail_flagged", extra={"request_id": request_id, "point": point,
                                                             "filters": verdict.filters,
                                                             "policy_mode": state.settings.model_armor_mode})
    return verdict


@router.post("/api/chat")
async def chat(request: Request, body: ChatRequest):
    if refused := forbidden_mutation(request):
        return refused
    user = current_user(request)
    if user is None:
        return unauthorized()
    state = request.app.state
    settings = state.settings
    store = state.conversations
    started = time.monotonic()
    question = body.question.strip()
    if not question:
        return JSONResponse({"detail": "question_empty"}, status_code=422)
    if len(question) > settings.max_input_chars:
        return refuse("input_too_long", 422, "question_too_long")
    conversation = None
    if body.conversationId is not None:
        try:
            conversation = await store.get(user.username, body.conversationId) if valid_id(body.conversationId) else None
        except ConversationsUnavailable:
            return JSONResponse({"detail": "upstream_failed"}, status_code=503)
        if conversation is None:
            return JSONResponse({"detail": "not_found"}, status_code=404)
    # The benchmark account is exempt from the session rate limit, never from admission, so
    # benchmarks measure inference capacity.
    wait = 0 if user.rate_limit_exempt else state.rate_limiter.check(user.username)
    if wait:
        return refuse("rate_limit", 429, "rate_limited", wait)
    if not state.admission.try_acquire():
        return refuse("admission", 429, "busy", ADMISSION_RETRY_SECONDS)

    request_id = request.state.request_id
    blocking = settings.model_armor_mode == "block"

    async def retrieve():
        retrieval_started = time.monotonic()
        found = await state.retriever.retrieve(question)
        RAG_RETRIEVAL.observe(time.monotonic() - retrieval_started)
        return found

    try:
        # The question is screened while passages are retrieved, so the check adds little wait.
        verdict, passages = await asyncio.gather(screen(state, "question", question, request_id), retrieve())
        if blocking and verdict.flagged:
            state.admission.release()
            return refuse("policy", 422, "blocked_by_policy")
        # Retrieved passages are untrusted text: one carrying injected instructions is dropped.
        verdicts = await asyncio.gather(*(screen(state, "passage", p.text, request_id) for p in passages))
        if blocking:
            passages = [p for p, v in zip(passages, verdicts) if not v.flagged]
        budget = Budget(settings.context_tokens, settings.output_tokens, settings.passage_tokens, settings.history_turns)
        fitted = await fit_prompt(question, history(conversation) if conversation else [], passages, state.backend, budget)
        conversation_id = conversation.id if conversation else await store.create(user.username, question[:64])
        await store.add_message(user.username, conversation_id, StoredMessage("user", question, "complete", []))
    except ConversationsUnavailable:
        state.admission.release()
        RAG_REQUESTS.labels("upstream_failed").inc()
        return JSONResponse({"detail": "upstream_failed"}, status_code=503)
    except BudgetExceeded:
        state.admission.release()
        return refuse("input_too_long", 422, "question_too_long")
    except RetrievalUnavailable:
        state.admission.release()
        RAG_REQUESTS.labels("retrieval_unavailable").inc()
        return JSONResponse({"detail": "retrieval_unavailable"}, status_code=503)
    except UpstreamError as exc:
        state.admission.release()
        outcome = "model_unavailable" if isinstance(exc, ModelUnavailable) else "upstream_failed"
        RAG_REQUESTS.labels(outcome).inc()
        return JSONResponse({"detail": outcome}, status_code=503)
    except BaseException:
        state.admission.release()
        raise

    stream = stream_answer(state, fitted, request_id, started, user.username, conversation_id)
    return StreamingResponse(stream, media_type="text/event-stream", headers={"Cache-Control": "no-store"})


def source_list(fitted: FittedPrompt) -> list[dict]:
    return [{"label": f"S{n}", "chunkId": p.chunk_id, "title": p.title, "headingPath": p.heading_path,
             "url": p.url, "score": round(p.score, 4)} for n, p in enumerate(fitted.passages, start=1)]


async def bounded(events: AsyncIterator, stall_seconds: float, deadline: float,
                  first_seconds: float | None = None) -> AsyncIterator:
    """Yields upstream events, failing when one takes longer than the stall timeout or the deadline.
    The first event may take up to first_seconds instead, because it waits for a free slot and the
    whole prompt to be processed.

    Each wait gets its own timeout and nothing is yielded inside one, because a timeout spanning a
    yield would cancel whatever the consumer is awaiting instead of this stream.
    """
    limit = first_seconds or stall_seconds
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DeadlineReached
            wait = min(limit, remaining)
            try:
                async with asyncio.timeout(wait):
                    event = await anext(events)
            except StopAsyncIteration:
                return
            except TimeoutError:
                raise (Stalled if wait == limit else DeadlineReached) from None
            limit = stall_seconds
            yield event
    finally:
        # Closing the upstream request frees the model server's slot. The shield lets the close
        # finish even when the stream is being cancelled because the client went away.
        with anyio.CancelScope(shield=True):
            await events.aclose()


async def stream_answer(state, fitted: FittedPrompt, request_id: str, started: float, username: str,
                        conversation_id: str) -> AsyncIterator[str]:
    settings = state.settings
    backend: InferenceBackend = state.backend
    outcome = "upstream_failed"
    parts: list[str] = []
    ttft: float | None = None
    finish: Finish | None = None
    citations = None
    withheld = False
    deadline = started + settings.request_deadline_seconds
    guarded = bounded(backend.chat_stream(fitted.messages, settings.output_tokens), settings.stall_timeout_seconds, deadline,
                      settings.first_token_timeout_seconds)
    RAG_ACTIVE_STREAMS.inc()
    try:
        yield sse("meta", {
            "requestId": request_id,
            "conversationId": conversation_id,
            "promptVersion": PROMPT_VERSION,
            "model": backend.model_info().get("alias"),
            # documentation: grounded in the sources below; general: no passage was relevant.
            "mode": "documentation" if fitted.passages else "general",
            "sources": source_list(fitted),
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
            # The finished answer is screened before the terminal event. In block mode a flagged
            # answer is withheld: the interface replaces it, and the saved answer is the notice.
            policy = None
            answer = await screen(state, "answer", "".join(parts), request_id)
            if settings.model_armor_mode == "block" and answer.flagged:
                policy = {"withheld": True, "filters": answer.filters}
                withheld = True
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
                **({"policy": policy} if policy else {}),
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
        # The answer is saved however the stream ended, with its sources' titles and links.
        sources = source_list(fitted)
        try:
            with anyio.CancelScope(shield=True):
                await state.conversations.add_message(username, conversation_id, StoredMessage(
                    "assistant", WITHHELD if withheld else "".join(parts), SAVED_STATUS.get(outcome, "failed"),
                    [] if withheld else sources))
        except ConversationsUnavailable:
            state.logger.error("answer_not_saved", extra={"request_id": request_id, "error_type": "ConversationsUnavailable"})
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
