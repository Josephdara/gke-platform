from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI

from .config import Settings
from .logging import RequestLoggingMiddleware, create_logger
from .routes import router


def create_app(settings: Settings | None = None, logger: logging.Logger | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings.from_env()
    logger = logger if logger is not None else create_logger(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.ready = True
        logger.info("application_started")
        try:
            yield
        finally:
            app.state.ready = False
            logger.info("application_stopped")

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.ready = False
    app.state.logger = logger
    app.include_router(router)
    app.add_middleware(RequestLoggingMiddleware, logger=logger)
    return app
