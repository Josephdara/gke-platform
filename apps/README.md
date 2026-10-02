# Applications

These are the services the platform deploys. Each service has its own README with its interface, configuration, and design. This page shows you how to test the Python service and build and run its container image. To deploy an image to Kubernetes, see the [platform README](../platform/README.md).

| Service | Contents |
| --- | --- |
| [`platform-verification-api/`](platform-verification-api/) | FastAPI service I use to verify deployment, health, configuration, and logging. See its [README](platform-verification-api/README.md) |

## Testing the Python service

From `apps/platform-verification-api/`, create the virtual environment and run the tests:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m pytest
.venv/bin/python -m pip check
```

All 44 tests pass for me. The process tests start the real server and send it SIGTERM; they are skipped if your environment does not allow binding a local socket.

## Building and running the container image

You don't need to build the image for GKE yourself: merges to `main` that change the API build, scan, and publish it. See the [pipeline README](../pipeline/README.md). The commands below are for trying the image locally.

Run these from the repository root.

Build for GKE, whose nodes are `linux/amd64`. On Apple Silicon this build and the container run under emulation:

```sh
docker build --platform linux/amd64 \
  -t platform-verification-api:local \
  ./apps/platform-verification-api
```

Build for the local Docker Desktop cluster, which runs `linux/arm64` on Apple Silicon:

```sh
docker build --platform linux/arm64 \
  -t platform-verification-api:local-arm64 \
  ./apps/platform-verification-api
```

Run the amd64 image. `ENVIRONMENT` and `RELEASE_VERSION` are required; without them the container exits with code 2:

```sh
docker run --rm --platform linux/amd64 -p 8080:8080 \
  -e ENVIRONMENT=local -e RELEASE_VERSION=dev \
  platform-verification-api:local
```

From another terminal, check the three routes:

```sh
curl -s http://localhost:8080/
curl -s http://localhost:8080/livez
curl -s http://localhost:8080/readyz
```

Expect `{"service":"platform-verification-api","version":"dev"}`, `{"status":"alive"}`, and `{"status":"ready"}`. The logs show the `/` request at INFO; successful `/livez` and `/readyz` requests log at DEBUG, so they do not appear at the default level.

The `platform-verification-api:local` tag is for local Docker use only. The chart references images by registry digest, never by tag.
