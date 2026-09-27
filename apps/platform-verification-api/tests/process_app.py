"""Test-only slow request using the production server configuration."""

import asyncio
import os
import socket

from platform_verification_api.app import create_app
from platform_verification_api.config import Settings
from platform_verification_api.server import build_server


if __name__ == "__main__":
    settings = Settings.from_env()
    app = create_app(settings)

    @app.get("/test-slow")
    async def slow():
        app.state.logger.info("test_request_started")
        await asyncio.sleep(1)
        return {"status": "completed"}

    with socket.socket(fileno=int(os.environ["TEST_SOCKET_FD"])) as listener:
        build_server(app, settings).run(sockets=[listener])
