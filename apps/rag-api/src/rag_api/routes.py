from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

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
    retrieval_ok = await state.retriever.health()
    return {
        "model": {**state.backend.model_info(), "status": "ok" if model_ok else "unavailable"},
        "retrieval": {"status": "ok" if retrieval_ok else "unavailable"},
        "promptVersion": PROMPT_VERSION,
        "admission": {"active": state.admission.active, "limit": state.admission.limit},
    }
