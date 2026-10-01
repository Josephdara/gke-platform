# Applications

Application source for the services the platform deploys. Each service has its own README with its interface, configuration, and design. This page covers testing the Python service and building and running its container image. Deploying an image to Kubernetes is described in the [platform README](../platform/README.md).

| Service | Contents |
| --- | --- |
| [`platform-verification-api/`](platform-verification-api/) | FastAPI service used to verify deployment, health, configuration, and logging. See its [README](platform-verification-api/README.md) |

## Testing the Python service

From `apps/platform-verification-api/`:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m pytest
.venv/bin/python -m pip check
```

Current result: 44 tests pass. The process tests start the real server and send it SIGTERM; they are skipped when the environment does not allow binding a local socket.

## Building and running the container image

Run from the repository root.

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

Run the amd64 image. `ENVIRONMENT` and `RELEASE_VERSION` are required; the container exits with code 2 without them:

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

Expected responses: `{"service":"platform-verification-api","version":"dev"}`, `{"status":"alive"}`, and `{"status":"ready"}`. The logs show the `/` request at INFO; successful `/livez` and `/readyz` requests log at DEBUG and do not appear at the default level.

Run with the same restrictions the chart applies: read-only root filesystem, all capabilities dropped, and no privilege escalation. The image supplies the non-root user (`10001:10001`):

```sh
docker run --rm --name pva-hardened --platform linux/amd64 -p 8080:8080 \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  -e ENVIRONMENT=local -e RELEASE_VERSION=dev \
  platform-verification-api:local
```

From another terminal, confirm the restrictions inside the running container:

```sh
docker exec pva-hardened id
docker exec pva-hardened sh -c 'touch /app/probe-write; touch /tmp/probe-write'
docker exec pva-hardened grep -E 'CapEff|NoNewPrivs|Seccomp' /proc/1/status
```

Expected: `uid=10001(app) gid=10001(app)`, `Read-only file system` for both writes, `CapEff: 0000000000000000`, `NoNewPrivs: 1`, and `Seccomp: 2` (filtering active). The three routes still respond as above.

The `platform-verification-api:local` tag is for local Docker use only. The chart references images by registry digest, never by tag; see [Local deployment on Docker Desktop](../platform/README.md#local-deployment-on-docker-desktop).

