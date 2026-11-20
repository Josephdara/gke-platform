from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from .retrieval import RetrievalUnavailable

from .prompt import PROMPT_VERSION

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


@router.get("/api/status")
async def status(request: Request) -> dict:
    state = request.app.state
    model_ok = await state.backend.health()
    return {
        "model": {**state.backend.model_info(), "status": "ok" if model_ok else "unavailable"},
        # ok, unavailable, mismatch (vectors from another embedding model), or disabled.
        "retrieval": {"status": await state.retriever.status()},
        "promptVersion": PROMPT_VERSION,
        "admission": {"active": state.admission.active, "limit": state.admission.limit},
    }


@router.get("/api/sources/{chunk_id}")
async def source(request: Request, chunk_id: str) -> JSONResponse:
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
