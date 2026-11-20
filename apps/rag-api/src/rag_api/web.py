"""The built frontend, and the security headers on every response."""

from pathlib import Path

from fastapi import APIRouter, Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# The frontend loads only its own scripts, styles, and API; nothing may frame it.
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'")


class SecurityHeaders:
    """Pure ASGI, so streamed answers pass through unbuffered."""

    def __init__(self, app: ASGIApp, hsts: bool):
        self.app = app
        self.headers = [
            (b"content-security-policy", CSP.encode()),
            (b"x-content-type-options", b"nosniff"),
            (b"referrer-policy", b"no-referrer"),
            (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
        ]
        if hsts:
            self.headers.append((b"strict-transport-security", b"max-age=31536000"))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def respond(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []), *self.headers]}
            await send(message)

        await self.app(scope, receive, respond)


def frontend_router(static_dir: str) -> APIRouter:
    """Serves the built frontend: real files as they are, any other page path as index.html, so
    the app handles its own routes. Unknown API paths stay JSON 404s."""
    root = Path(static_dir).resolve()
    index = root / "index.html"
    router = APIRouter()

    @router.get("/{path:path}", include_in_schema=False)
    async def page(request: Request, path: str) -> Response:
        if path == "api" or path.startswith("api/"):
            return JSONResponse({"detail": "not_found"}, status_code=404)
        target = (root / path).resolve()
        if path and target.is_relative_to(root) and target.is_file():
            # Vite names assets by their content hash, so they never change under one name.
            cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
            return FileResponse(target, headers={"Cache-Control": cache})
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return router
