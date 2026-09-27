# Build context: apps/platform-verification-api. Select linux/amd64 for GKE.
FROM python:3.14.7-slim-bookworm@sha256:9ab8d9c8514b44f90cf0029dd42fdd7e9e211e639c8b995304cc04568dee900f

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    APP_PORT=8080

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check \
        --only-binary=:all: -r requirements.txt \
    && python -m pip check

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --no-log-init \
        --home-dir /nonexistent --shell /usr/sbin/nologin app

# Root-owned source is readable, but not writable, by the runtime user.
COPY src/ ./src/

USER 10001:10001

EXPOSE 8080
STOPSIGNAL SIGTERM

# ENVIRONMENT and RELEASE_VERSION are required runtime inputs.
# Exec form delivers signals directly to the server, without a shell wrapper.
CMD ["python", "-m", "platform_verification_api"]
