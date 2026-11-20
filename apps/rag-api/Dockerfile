# Build context: apps/rag-api. Select linux/amd64 for GKE.

# Stage 1: the frontend, built with Node. Nothing from this stage but the static files reaches
# the runtime image.
FROM node:26-slim@sha256:e6bedef217677b276c591795e169840edd9096dbf13f29df8ef8d1856b8820bc AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: the API, on the same pinned Python base as the other services.
FROM python:3.14.10-slim-bookworm@sha256:3fe1a0b6c2d6b2ebb572906cdabeca75aeb558c0c17db5ffefbcf8094871c32b

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    APP_PORT=8080 \
    STATIC_DIR=/app/static

WORKDIR /app

COPY requirements.txt ./requirements.txt
# pip is only needed at build time; removing it also removes its vendored libraries.
RUN python -m pip install --no-cache-dir --disable-pip-version-check \
        --only-binary=:all: -r requirements.txt \
    && python -m pip check \
    && python -m pip uninstall --yes --disable-pip-version-check pip

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --no-log-init \
        --home-dir /nonexistent --shell /usr/sbin/nologin app

# Root-owned code and static files are readable, but not writable, by the runtime user.
COPY src/ ./src/
COPY --from=frontend /frontend/dist/ ./static/

USER 10001:10001

EXPOSE 8080 9090
STOPSIGNAL SIGTERM

# MODEL_URL, USERS_FILE, SESSION_KEY_FILE, and ALLOWED_ORIGIN are required runtime inputs.
CMD ["python", "-m", "rag_api"]
