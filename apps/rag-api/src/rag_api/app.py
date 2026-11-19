from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI

from .chat import router as chat_router
from .config import Settings
from .inference import InferenceBackend, LlamaCppBackend, create_model_client
from .limits import AdmissionLimiter, RateLimiter
from .logging import RequestLoggingMiddleware, create_logger
from .retrieval import NoRetriever, Retriever
from .routes import router


def create_app(
    settings: Settings | None = None,
    logger: logging.Logger | None = None,
    backend: InferenceBackend | None = None,
    retriever: Retriever | None = None,
) -> FastAPI:
    settings = settings if settings is not None else Settings.from_env()
    logger = logger if logger is not None else create_logger(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = None
        if app.state.backend is None:
            # A read timeout above the stall timeout, so the stall check fires first.
            client = create_model_client(settings.model_url, read_seconds=settings.stall_timeout_seconds + 5)
            app.state.backend = LlamaCppBackend(client, settings.model_alias)
        app.state.ready = True
        logger.info("application_started")
        try:
            yield
        finally:
            app.state.ready = False
            if client is not None:
                await client.aclose()
            logger.info("application_stopped")

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.ready = False
    app.state.logger = logger
    app.state.backend = backend
    app.state.retriever = retriever if retriever is not None else NoRetriever()
    app.state.admission = AdmissionLimiter(settings.admission_limit)
    app.state.rate_limiter = RateLimiter(settings.rate_limit_per_minute)
    app.include_router(router)
    app.include_router(chat_router)
    app.add_middleware(RequestLoggingMiddleware, logger=logger)
    return app
