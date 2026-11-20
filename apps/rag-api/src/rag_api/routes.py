import anyio
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from starlette.responses import JSONResponse, Response

from .auth import COOKIE, client_address, current_user, forbidden_mutation, unauthorized
from .conversations import ConversationsUnavailable, valid_id
from .prompt import PROMPT_VERSION
from .retrieval import RetrievalUnavailable

router = APIRouter()


@router.get("/healthz")
async def liveness() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/readyz")
async def readiness(request: Request) -> JSONResponse:
    # Readiness covers only this process. A model server outage shows in /api/status and in
    # the interface, instead of removing every rag-api replica from the load balancer.
    ready = request.app.state.ready
    return JSONResponse({"status": "ready" if ready else "not_ready"}, status_code=200 if ready else 503)


class SignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    password: str


@router.get("/api/session")
async def session(request: Request) -> JSONResponse:
    user = current_user(request)
    return JSONResponse({"username": user.username}) if user else unauthorized()


@router.post("/api/session")
async def sign_in(request: Request, body: SignIn) -> Response:
    if refused := forbidden_mutation(request):
        return refused
    state = request.app.state
    settings = state.settings
    # Attempts are limited per address and per username, so neither a single client nor a
    # spread of clients can guess one account's password quickly.
    address = client_address(request, settings.forwarded_hops)
    wait = max(state.login_limiter.check(f"address:{address}"), state.login_limiter.check(f"user:{body.username[:64]}"))
    if wait:
        return JSONResponse({"detail": "rate_limited"}, status_code=429, headers={"Retry-After": str(wait)})
    # scrypt takes tens of milliseconds, so it runs off the event loop.
    user = await anyio.to_thread.run_sync(state.sessions.authenticate, body.username, body.password)
    if user is None:
        state.logger.warning("sign_in_failed", extra={"request_id": request.state.request_id})
        return JSONResponse({"detail": "invalid_credentials"}, status_code=401)
    response = Response(status_code=204)
    response.set_cookie(COOKIE, state.sessions.issue(user), max_age=settings.session_hours * 3600,
                        httponly=True, secure=settings.cookie_secure, samesite="strict", path="/")
    return response


@router.delete("/api/session")
async def sign_out(request: Request) -> Response:
    if refused := forbidden_mutation(request):
        return refused
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, httponly=True, secure=request.app.state.settings.cookie_secure,
                           samesite="strict", path="/")
    return response


@router.get("/api/status")
async def status(request: Request) -> JSONResponse:
    if not current_user(request):
        return unauthorized()
    state = request.app.state
    model_ok = await state.backend.health()
    return JSONResponse({
        "model": {**state.backend.model_info(), "status": "ok" if model_ok else "unavailable"},
        # ok, unavailable, mismatch (vectors from another embedding model), or disabled.
        "retrieval": {"status": await state.retriever.status()},
        "promptVersion": PROMPT_VERSION,
        "admission": {"active": state.admission.active, "limit": state.admission.limit},
    })


@router.get("/api/sources/{chunk_id}")
async def source(request: Request, chunk_id: str) -> JSONResponse:
    if not current_user(request):
        return unauthorized()
    try:
        found = await request.app.state.retriever.source(chunk_id)
    except RetrievalUnavailable:
        return JSONResponse({"detail": "retrieval_unavailable"}, status_code=503)
    if found is None:
        # Unknown, retired, or superseded by a newer revision of its document.
        return JSONResponse({"detail": "not_found"}, status_code=404)
    return JSONResponse({
        "chunkId": found.chunk_id, "documentTitle": found.document_title, "headingPath": found.heading_path,
        "text": found.text, "sourceUrl": found.source_url, "license": found.license, "attribution": found.attribution,
    })


@router.get("/api/conversations")
async def conversations(request: Request) -> JSONResponse:
    user = current_user(request)
    if not user:
        return unauthorized()
    try:
        found = await request.app.state.conversations.list(user.username)
    except ConversationsUnavailable:
        return JSONResponse({"detail": "upstream_failed"}, status_code=503)
    return JSONResponse([{"id": c.id, "title": c.title, "updatedAt": c.updated_at} for c in found])


@router.get("/api/conversations/{conversation_id}")
async def conversation(request: Request, conversation_id: str) -> JSONResponse:
    user = current_user(request)
    if not user:
        return unauthorized()
    try:
        found = await request.app.state.conversations.get(user.username, conversation_id) if valid_id(conversation_id) else None
    except ConversationsUnavailable:
        return JSONResponse({"detail": "upstream_failed"}, status_code=503)
    if found is None:
        # Another user's conversation is indistinguishable from one that does not exist.
        return JSONResponse({"detail": "not_found"}, status_code=404)
    return JSONResponse({"id": found.id, "title": found.title, "messages": [
        {"role": m.role, "content": m.content, "status": m.status, "sources": m.sources} for m in found.messages]})


@router.delete("/api/conversations/{conversation_id}")
async def delete_conversation(request: Request, conversation_id: str) -> Response:
    if refused := forbidden_mutation(request):
        return refused
    user = current_user(request)
    if not user:
        return unauthorized()
    try:
        deleted = valid_id(conversation_id) and await request.app.state.conversations.delete(user.username, conversation_id)
    except ConversationsUnavailable:
        return JSONResponse({"detail": "upstream_failed"}, status_code=503)
    return Response(status_code=204) if deleted else JSONResponse({"detail": "not_found"}, status_code=404)
