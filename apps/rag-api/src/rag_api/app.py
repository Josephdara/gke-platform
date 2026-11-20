from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI

from .chat import router as chat_router
from .config import Settings
from .inference import InferenceBackend, LlamaCppBackend, create_model_client
from .limits import AdmissionLimiter, RateLimiter
from .logging import RequestLoggingMiddleware, create_logger
from .retrieval import NoRetriever, PgCorpusStore, PgVectorRetriever, Retriever, TeiEmbeddings
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
        clients = []
        if app.state.backend is None:
            # A read timeout above the stall timeout, so the stall check fires first.
            clients.append(create_model_client(settings.model_url, read_seconds=settings.stall_timeout_seconds + 5))
            app.state.backend = LlamaCppBackend(clients[-1], settings.model_alias)
        if app.state.retriever is None:
            app.state.retriever = build_retriever(settings, clients)
        app.state.ready = True
        logger.info("application_started")
        try:
            yield
        finally:
            app.state.ready = False
            for client in clients:
                await client.aclose()
            logger.info("application_stopped")

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.ready = False
    app.state.logger = logger
    app.state.backend = backend
    app.state.retriever = retriever
    app.state.admission = AdmissionLimiter(settings.admission_limit)
    app.state.rate_limiter = RateLimiter(settings.rate_limit_per_minute)
    app.include_router(router)
    app.include_router(chat_router)
    app.add_middleware(RequestLoggingMiddleware, logger=logger)
    return app


def build_retriever(settings: Settings, clients: list) -> Retriever:
    if settings.database_host is None:
        return NoRetriever()
    # Read once at startup; a rotated password takes effect when the Pod restarts.
    with open(settings.database_password_file) as handle:
        password = handle.read().strip()
    store = PgCorpusStore({"host": settings.database_host, "port": settings.database_port,
                           "dbname": settings.database_name, "user": settings.database_user, "password": password})
    clients.append(create_model_client(settings.embeddings_url, read_seconds=15))
    return PgVectorRetriever(store, TeiEmbeddings(clients[-1], settings.embedding_dimensions), settings)
