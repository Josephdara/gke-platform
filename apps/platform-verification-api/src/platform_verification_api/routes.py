from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

router = APIRouter()


@router.get("/")
async def identity(request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    return {"service": settings.service_name, "version": settings.release_version}


@router.get("/livez")
async def liveness() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/readyz")
async def readiness(request: Request) -> JSONResponse:
    ready = request.app.state.ready
    return JSONResponse({"status": "ready" if ready else "not_ready"}, status_code=200 if ready else 503)
