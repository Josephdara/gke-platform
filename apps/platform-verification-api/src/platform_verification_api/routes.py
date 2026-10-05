from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from .secret import SecretFile

router = APIRouter()


def refreshed_secret(request: Request) -> SecretFile | None:
    secret = request.app.state.secret
    if secret is not None:
        secret.refresh()
    return secret


@router.get("/")
async def identity(request: Request) -> dict[str, str | None]:
    settings = request.app.state.settings
    body = {"service": settings.service_name, "version": settings.release_version}
    secret = refreshed_secret(request)
    if secret is not None:
        body["secretLabel"] = secret.label
    return body


@router.get("/livez")
async def liveness() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/readyz")
async def readiness(request: Request) -> JSONResponse:
    secret = refreshed_secret(request)
    ready = request.app.state.ready and (secret is None or secret.label is not None)
    return JSONResponse({"status": "ready" if ready else "not_ready"}, status_code=200 if ready else 503)
