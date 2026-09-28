# Build context: apps/platform-verification-api. Select linux/amd64 for GKE.
FROM python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    APP_PORT=8080

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

# Root-owned source is readable, but not writable, by the runtime user.
COPY src/ ./src/

USER 10001:10001

EXPOSE 8080
STOPSIGNAL SIGTERM

# ENVIRONMENT and RELEASE_VERSION are required runtime inputs.
# Exec form delivers signals directly to the server, without a shell wrapper.
CMD ["python", "-m", "platform_verification_api"]
