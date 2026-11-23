from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
import httpx

from .auth import Sessions, load_key, load_users
from .chat import router as chat_router
from .config import Settings
from .conversations import ConversationStore, MemoryConversationStore, PgConversationStore
from .guardrails import MetadataToken, ModelArmor, NoGuardrail
from .inference import InferenceBackend, LlamaCppBackend, create_model_client
from .limits import AdmissionLimiter, RateLimiter
from .logging import RequestLoggingMiddleware, create_logger
from .retrieval import NoRetriever, PgCorpusStore, PgVectorRetriever, Retriever, TeiEmbeddings
from .routes import router
from .web import SecurityHeaders, frontend_router


def create_app(
    settings: Settings | None = None,
    logger: logging.Logger | None = None,
    backend: InferenceBackend | None = None,
    retriever: Retriever | None = None,
    conversations: ConversationStore | None = None,
    guardrail=None,
) -> FastAPI:
    settings = settings if settings is not None else Settings.from_env()
    logger = logger if logger is not None else create_logger(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        clients = []
        if app.state.backend is None:
            # A read timeout above both token timeouts, so rag-api's own checks fire first.
            clients.append(create_model_client(settings.model_url, read_seconds=settings.first_token_timeout_seconds + 5))
            app.state.backend = LlamaCppBackend(clients[-1], settings.model_alias)
        if app.state.retriever is None:
            app.state.retriever = build_retriever(settings, clients)
        if app.state.conversations is None:
            app.state.conversations = build_conversations(settings)
        if app.state.guardrail is None:
            app.state.guardrail = build_guardrail(settings, clients)
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
    app.state.conversations = conversations
    app.state.guardrail = guardrail
    # Read once at startup; a rotated users file or session key takes effect when the Pod restarts.
    app.state.sessions = Sessions(load_users(settings.users_file), load_key(settings.session_key_file),
                                  settings.session_hours * 3600)
    app.state.admission = AdmissionLimiter(settings.admission_limit)
    app.state.rate_limiter = RateLimiter(settings.rate_limit_per_minute)
    app.state.login_limiter = RateLimiter(settings.login_attempts_per_minute)
    app.include_router(router)
    app.include_router(chat_router)
    if settings.static_dir:
        app.include_router(frontend_router(settings.static_dir))
    app.add_middleware(SecurityHeaders, hsts=settings.cookie_secure)
    app.add_middleware(RequestLoggingMiddleware, logger=logger)
    return app


def database(settings: Settings) -> dict:
    # Read once at startup; a rotated password takes effect when the Pod restarts.
    with open(settings.database_password_file) as handle:
        password = handle.read().strip()
    return {"host": settings.database_host, "port": settings.database_port, "dbname": settings.database_name,
            "user": settings.database_user, "password": password}


def build_conversations(settings: Settings) -> ConversationStore:
    # Without a database, conversations live in memory until the process restarts.
    return PgConversationStore(database(settings)) if settings.database_host else MemoryConversationStore()


def build_guardrail(settings: Settings, clients: list):
    if settings.model_armor_mode == "off":
        return NoGuardrail()
    clients.append(httpx.AsyncClient(timeout=3))
    token = MetadataToken(clients[-1])
    clients.append(httpx.AsyncClient(timeout=5))
    return ModelArmor(clients[-1], settings.model_armor_template, token)


def build_retriever(settings: Settings, clients: list) -> Retriever:
    if settings.database_host is None:
        return NoRetriever()
    store = PgCorpusStore(database(settings))
    clients.append(create_model_client(settings.embeddings_url, read_seconds=15))
    return PgVectorRetriever(store, TeiEmbeddings(clients[-1], settings.embedding_dimensions), settings)
