"""Test-only server: the production server configuration with a slow fake model."""

import os
import socket

from rag_api.app import create_app
from rag_api.config import Settings
from rag_api.server import build_server

from fake_model import FakeModelServer


if __name__ == "__main__":
    settings = Settings.from_env()
    model = FakeModelServer(tokens=["slow "] * 10, delay=0.1)
    app = create_app(settings, backend=model.backend())
    with socket.socket(fileno=int(os.environ["TEST_SOCKET_FD"])) as listener:
        build_server(app, settings).run(sockets=[listener])
