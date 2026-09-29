# GKE Application Platform

A reusable application deployment platform on GKE, built with Terraform, Kubernetes, Argo CD, Helm, Kyverno, Cloud Build, and Docker. Developers deploy a service through a reviewed configuration change, with secure defaults, health checks, and Git-based recovery. The design reference is [architecture.md](architecture.md).

The platform runs in my personal GCP project `gke-build-proj`, as a temporary staging environment with a $100 budget and a 24-hour environment lifecycle. The chart's `project` value matches the project ID, so Kubernetes names (`<project>-<environment>-<service>`) line up with GCP names (`<project>-<environment>-<purpose>`).

## Repository layout


| Path                                                                                           | Contents                                                                                                                                  |
| ---------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `[apps/platform-verification-api/](apps/platform-verification-api/)`                           | FastAPI service used to verify deployment, health, configuration, and logging. See its [README](apps/platform-verification-api/README.md) |
| `[platform/charts/service/](platform/charts/service/)`                                         | Shared Helm chart that deploys one HTTP service                                                                                           |
| `[platform/services/platform-verification-api/](platform/services/platform-verification-api/)` | Chart values for the API: `values.yaml` (shared) plus one environment file, `values-staging.yaml` or `values-local.yaml`                  |
| `[platform/namespaces/](platform/namespaces/)`                                                 | Local namespace manifest that enforces the Pod Security "restricted" profile                                                              |
| `[platform/tests/](platform/tests/)`                                                           | Chart validation script; its fixtures live in `platform/charts/service/tests/fixtures/`                                                   |
| `[architecture.md](architecture.md)`                                                           | Architecture and design decisions                                                                                                         |
| `infra/`, `pipeline/`                                                                          | TBD                                                                                                                                       |




## Current status


| Build                                                                                                                            | Status      |
| -------------------------------------------------------------------------------------------------------------------------------- | ----------- |
| Architecture and design decisions                                                                                                | Done        |
| Verification service and shared Helm chart                                                                                       | Done        |
| GCP foundation: Terraform, GKE, Artifact Registry, IAM, budget controls                                                          | In Progress |
| Image build pipeline: Cloud Build, recorded digests                                                                              | Planned     |
| GitOps deployment: Argo CD, OCI bundles                                                                                          | Planned     |
| Identity and isolation, admission policies, validation suite, second service, observability and costs, acceptance tests, handoff | Planned     |


**Service and chart, done:**

- API with liveness (`/livez`), readiness (`/readyz`), and identity (`/`) routes, validated configuration, JSON logs with request IDs, graceful shutdown, and tests.
- Successful health-check requests log at DEBUG; a not-ready `/readyz` response logs at WARNING.
- Dockerfile with a digest-pinned base image and a numeric non-root user. pip is removed from the runtime image after dependencies are installed.
- Trivy policy gate passes: no fixable HIGH or CRITICAL vulnerabilities (Trivy 0.74.0, vulnerability database of 2026-09-28).
- Runtime security verified in Docker and in Kubernetes: user `10001`, read-only root filesystem, no effective capabilities, no privilege escalation, and seccomp filtering active.
- Local deployment on Docker Desktop Kubernetes from a local registry, into a namespace that enforces the Pod Security "restricted" profile. All checks in [Local deployment on Docker Desktop](#local-deployment-on-docker-desktop) passed on 2026-09-28, as run and reported by the owner.
- Shared chart with a ServiceAccount, ConfigMap, Deployment, and ClusterIP Service:
  - Names derived as `<project>-<environment>-<serviceName>`, failing above 63 characters.
  - Namespace derived as `<project>-<environment>`; rendering fails unless the release namespace matches.
  - Nine labels, including the required `project`, `environment`, `service`, and `owner`. Selectors use only `app.kubernetes.io/name` and `app.kubernetes.io/instance`.
  - Image referenced by digest only, with no tag.
  - Startup, liveness, and readiness probes on the named container port `app-http`.
  - Pod security: non-root, `RuntimeDefault` seccomp, read-only root filesystem, all capabilities dropped, no privilege escalation, no service account token.
  - Rolling updates with one surge pod and zero unavailable pods, and a 30-second termination grace period.
  - Values schema (`values.schema.json`) that rejects missing, unknown, and malformed inputs during lint and rendering; requests above limits fail during rendering.
- API values split into a shared `values.yaml` and one file per environment (`values-staging.yaml`, `values-local.yaml`). The shared file does not render on its own.
- [Validation script](#validating-the-chart) with 27 checks: application tests; lint, rendering, and strict Kubernetes schema validation for staging, local, and a second sample service that proves the chart renders another service without template changes; 15 invalid fixtures that must fail with the expected message; and wrong-namespace and shared-values-alone checks.

**Service and chart, planned changes:**

- Consistency checks across rendered resources (selectors, port names, and resource references) and a recorded format for Trivy exceptions.
- Fix for the `KeyboardInterrupt` traceback after Ctrl+C.

The image repository and digest in `values-staging.yaml` are placeholders (`sample-registry.invalid`, all-zero digest). `values-local.yaml` points at the local registry and the digest it reported.

## Tool versions

These versions were used to build and test the current state:


| Tool        | Version |
| ----------- | ------- |
| Python      | 3.14.6  |
| Helm        | 4.3.0   |
| kubectl     | 1.37.0  |
| Docker      | 29.8.0  |
| Trivy       | 0.74.0  |
| kubeconform | 0.8.0   |




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

The `platform-verification-api:local` tag is for local Docker use only. The chart references images by registry digest, never by tag; see [Local deployment on Docker Desktop](#local-deployment-on-docker-desktop).

## Local deployment on Docker Desktop

All checks in this section passed on 2026-09-28, as run and reported by the owner. Run from the repository root.

### Prerequisites

- Docker Desktop with Kubernetes enabled (kubeadm, single node). On Apple Silicon the node is `arm64`.
- Every `kubectl` command names `--context docker-desktop`, so no command reaches another cluster.

```sh
kubectl config get-contexts
kubectl --context docker-desktop get nodes -L kubernetes.io/arch
```

Start a local registry on port 5001, bound to `127.0.0.1` only. Port 5000 is avoided because macOS AirPlay Receiver uses it:

```sh
docker run -d --restart unless-stopped -p 127.0.0.1:5001:5000 --name local-registry registry:2
curl -s http://localhost:5001/v2/_catalog
```



### Build, scan, and publish

Commit application changes first. The image tag uses the last commit that touched the application, so it names the exact source. This must print nothing:

```sh
git status --porcelain apps/platform-verification-api
```

Build for `arm64`:

```sh
docker build --platform linux/arm64 \
  -t localhost:5001/platform-verification-api:local-$(git log -1 --format=%h -- apps/platform-verification-api) \
  apps/platform-verification-api
```

Scan before publishing. Fixable HIGH or CRITICAL vulnerabilities block publication, and the gate exits with code 1 when any are found. The secret scan must report no findings, and the image user must be `10001:10001`:

```sh
trivy image --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 \
  localhost:5001/platform-verification-api:local-$(git log -1 --format=%h -- apps/platform-verification-api)
trivy image --scanners secret \
  localhost:5001/platform-verification-api:local-$(git log -1 --format=%h -- apps/platform-verification-api)
docker image inspect --format '{{.Config.User}}' \
  localhost:5001/platform-verification-api:local-$(git log -1 --format=%h -- apps/platform-verification-api)
```

Push, then read the digest the registry reports from the `Docker-Content-Digest` header:

```sh
docker push localhost:5001/platform-verification-api:local-$(git log -1 --format=%h -- apps/platform-verification-api)
curl -sI \
  -H 'Accept: application/vnd.oci.image.index.v1+json' \
  -H 'Accept: application/vnd.docker.distribution.manifest.list.v2+json' \
  -H 'Accept: application/vnd.oci.image.manifest.v1+json' \
  -H 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
  http://localhost:5001/v2/platform-verification-api/manifests/local-$(git log -1 --format=%h -- apps/platform-verification-api)
```

After every rebuild, set `image.digest` in `values-local.yaml` to that digest and `releaseVersion` to the new `local-<commit>` tag. Docker's local image ID is not a substitute for the registry digest.

### Deploy

Create the namespace and confirm its Pod Security labels:

```sh
kubectl --context docker-desktop apply -f platform/namespaces/gke-build-proj-local.yaml
kubectl --context docker-desktop get namespace gke-build-proj-local --show-labels
```

Render with both values files; the later file overrides the base. Then run a server-side dry run, which validates against the API schema and admission (including the "restricted" profile) without creating anything. Expect four `(server dry run)` lines and no warnings:

```sh
mkdir -p /tmp/pva-local /tmp/pva-tests
helm template platform-verification-api platform/charts/service \
  -f platform/services/platform-verification-api/values.yaml \
  -f platform/services/platform-verification-api/values-local.yaml \
  --namespace gke-build-proj-local > /tmp/pva-local/manifests.yaml
kubectl --context docker-desktop apply --dry-run=server -f /tmp/pva-local/manifests.yaml
```

Apply and wait for the rollout:

```sh
kubectl --context docker-desktop apply -f /tmp/pva-local/manifests.yaml
kubectl --context docker-desktop -n gke-build-proj-local rollout status \
  deployment/gke-build-proj-local-platform-verification-api --timeout=120s
```



### Checks

**A. Healthy start.** Two pods at `1/1`, no restarts, and no warning events:

```sh
kubectl --context docker-desktop -n gke-build-proj-local get pods -o wide
kubectl --context docker-desktop -n gke-build-proj-local get events --sort-by=.lastTimestamp
```

**B. Runtime security.** Expect `uid=10001(app)`, `Read-only file system` for both writes, `CapEff: 0000000000000000`, `NoNewPrivs: 1`, and `Seccomp: 2`:

```sh
kubectl --context docker-desktop -n gke-build-proj-local exec deploy/gke-build-proj-local-platform-verification-api -- id
kubectl --context docker-desktop -n gke-build-proj-local exec deploy/gke-build-proj-local-platform-verification-api -- sh -c 'touch /app/probe-write; touch /tmp/probe-write'
kubectl --context docker-desktop -n gke-build-proj-local exec deploy/gke-build-proj-local-platform-verification-api -- grep -E 'CapEff|NoNewPrivs|Seccomp' /proc/1/status
```

**C. "Restricted" is enforced.** A privileged pod, sent as a server-side dry run, must be refused with `violates PodSecurity "restricted:latest"`:

```sh
kubectl --context docker-desktop -n gke-build-proj-local run psa-test --dry-run=server --restart=Never \
  --image=localhost:5001/platform-verification-api:local-$(git log -1 --format=%h -- apps/platform-verification-api) \
  --overrides='{"spec":{"containers":[{"name":"psa-test","image":"busybox","securityContext":{"privileged":true}}]}}'
```

**D. Service routing.** The Service lists two pod IPs, and a one-off client pod that itself meets the "restricted" profile calls the Service by name. Expect `200`, a request ID, and the identity response with the local release:

```sh
kubectl --context docker-desktop -n gke-build-proj-local get endpointslices \
  -l kubernetes.io/service-name=gke-build-proj-local-platform-verification-api
```

```sh
cat > /tmp/pva-tests/svc-client.yaml <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: svc-client
  namespace: gke-build-proj-local
spec:
  restartPolicy: Never
  automountServiceAccountToken: false
  securityContext:
    runAsNonRoot: true
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: svc-client
      image: localhost:5001/platform-verification-api:local-$(git log -1 --format=%h -- apps/platform-verification-api)
      command: ["python", "-c", "import urllib.request as u; r = u.urlopen('http://gke-build-proj-local-platform-verification-api/'); print(r.status, r.headers['x-request-id'], r.read().decode())"]
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop: ["ALL"]
EOF
kubectl --context docker-desktop apply -f /tmp/pva-tests/svc-client.yaml
kubectl --context docker-desktop -n gke-build-proj-local wait --for=jsonpath='{.status.phase}'=Succeeded pod/svc-client --timeout=60s
kubectl --context docker-desktop -n gke-build-proj-local logs svc-client
kubectl --context docker-desktop -n gke-build-proj-local delete pod svc-client
```

**E. Logs.** JSON lines with `"environment": "local"`, the client's `/` request at INFO with the same request ID, and no health-check requests:

```sh
kubectl --context docker-desktop -n gke-build-proj-local logs \
  -l app.kubernetes.io/instance=gke-build-proj-local-platform-verification-api --prefix --tail=50
```

**F. Configuration change rolls the pods.** A different release version changes the ConfigMap checksum; the rollout adds one pod before removing an old one, and old pods log `application_stopped`. Follow an old pod's logs in a second terminal before applying (`kubectl --context docker-desktop -n gke-build-proj-local logs -f <pod>`):

```sh
helm template platform-verification-api platform/charts/service \
  -f platform/services/platform-verification-api/values.yaml \
  -f platform/services/platform-verification-api/values-local.yaml \
  --namespace gke-build-proj-local \
  --set releaseVersion=local-$(git log -1 --format=%h -- apps/platform-verification-api)-r2 > /tmp/pva-tests/r2.yaml
grep checksum/config /tmp/pva-local/manifests.yaml /tmp/pva-tests/r2.yaml
kubectl --context docker-desktop apply -f /tmp/pva-tests/r2.yaml
kubectl --context docker-desktop -n gke-build-proj-local rollout status \
  deployment/gke-build-proj-local-platform-verification-api --timeout=120s
kubectl --context docker-desktop -n gke-build-proj-local get replicasets
```

**G. Wrong readiness path.** The rollout stalls: the new pod stays `0/1`, the old pods keep serving, the Service endpoints do not change, and events show `Readiness probe failed ... 404`. The `rollout status` command is expected to time out:

```sh
helm template platform-verification-api platform/charts/service \
  -f platform/services/platform-verification-api/values.yaml \
  -f platform/services/platform-verification-api/values-local.yaml \
  --namespace gke-build-proj-local --set probes.readiness.path=/wrong-ready > /tmp/pva-tests/bad-ready.yaml
kubectl --context docker-desktop apply -f /tmp/pva-tests/bad-ready.yaml
kubectl --context docker-desktop -n gke-build-proj-local rollout status \
  deployment/gke-build-proj-local-platform-verification-api --timeout=60s
kubectl --context docker-desktop -n gke-build-proj-local get pods
kubectl --context docker-desktop -n gke-build-proj-local get events --field-selector reason=Unhealthy
```

**H. Wrong liveness path.** The startup probe uses the same path, fails after about 30 seconds, and the container restarts towards `CrashLoopBackOff` while the old pods stay `1/1`:

```sh
helm template platform-verification-api platform/charts/service \
  -f platform/services/platform-verification-api/values.yaml \
  -f platform/services/platform-verification-api/values-local.yaml \
  --namespace gke-build-proj-local --set probes.liveness.path=/wrong-live > /tmp/pva-tests/bad-live.yaml
kubectl --context docker-desktop apply -f /tmp/pva-tests/bad-live.yaml
kubectl --context docker-desktop -n gke-build-proj-local get pods -w
kubectl --context docker-desktop -n gke-build-proj-local get events --field-selector reason=Unhealthy
```

After checks F, G, and H, restore the committed configuration:

```sh
kubectl --context docker-desktop apply -f /tmp/pva-local/manifests.yaml
kubectl --context docker-desktop -n gke-build-proj-local rollout status \
  deployment/gke-build-proj-local-platform-verification-api --timeout=120s
```



### Clean up

Deleting the namespace removes everything the chart created. Stopping the registry keeps its images for the next session; `docker rm -f local-registry` removes it entirely:

```sh
kubectl --context docker-desktop delete namespace gke-build-proj-local
docker stop local-registry
```



## Validating the chart

One command runs the application tests and every chart check, and prints `PASS` or `FAIL` for each:

```sh
platform/tests/validate-chart.sh
```

Prerequisites: Helm, kubeconform (`brew install kubeconform`), and the application's virtual environment from [Testing the Python service](#testing-the-python-service). The script can run from any directory in the repository.

What it checks:


| Check             | Covers                                                                                                                                                                                            |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Application tests | The pytest suite in `apps/platform-verification-api/`                                                                                                                                             |
| Lint and render   | Staging (`values.yaml` + `values-staging.yaml`), local (`values.yaml` + `values-local.yaml`), and the second sample service in `platform/charts/service/tests/fixtures/valid/second-service.yaml` |
| Kubernetes schema | kubeconform in strict mode on each rendered configuration, so unknown or misspelled fields fail                                                                                                   |
| Invalid fixtures  | Each file in `platform/charts/service/tests/fixtures/invalid/` is layered on the staging configuration, must fail to render, and must fail with the text on its first line                        |
| Built-in failures | Rendering into the wrong namespace, and rendering the shared `values.yaml` alone, must both fail                                                                                                  |


Exit codes: `0` when every check passes, `1` when a check fails, and `2` when a tool is missing.

The Kubernetes schemas are pinned to version 1.36.1 (the `KUBERNETES_VERSION` variable in the script), matching the local Docker Desktop cluster; update it when the target cluster version is known. The first run downloads the schemas into `~/.cache/kubeconform`, so it needs internet access; later runs use the cache. Set `KUBECONFORM_CACHE` to use a different directory.

To add an invalid fixture, create a small values file in `platform/charts/service/tests/fixtures/invalid/` that changes one input, and make its first line `# expect: <text the error must contain>`. Match a short, stable part of the message, such as the field path.

A passing run ends with:

```text
27 passed, 0 failed
```



## Testing the Helm chart

Run from the repository root. Every render combines the shared `values.yaml` with exactly one environment file; the shared file alone fails schema validation because `environment`, `image`, and `releaseVersion` live in the environment files. The staging commands pass `--namespace gke-build-proj-staging`, because the chart derives the namespace from `project` and `environment` and refuses to render into any other.

Lint the chart:

```sh
helm lint platform/charts/service -f platform/services/platform-verification-api/values.yaml -f platform/services/platform-verification-api/values-staging.yaml --namespace gke-build-proj-staging
```

Render all resources (ServiceAccount, ConfigMap, Service, Deployment):

```sh
helm template platform-verification-api platform/charts/service -f platform/services/platform-verification-api/values.yaml -f platform/services/platform-verification-api/values-staging.yaml --namespace gke-build-proj-staging
```

Render one template:

```sh
helm template platform-verification-api platform/charts/service -f platform/services/platform-verification-api/values.yaml -f platform/services/platform-verification-api/values-staging.yaml --namespace gke-build-proj-staging --show-only templates/service.yaml
```

Render the local configuration. `values-local.yaml` sets `environment: local`, so the derived namespace is `gke-build-proj-local`:

```sh
helm template platform-verification-api platform/charts/service -f platform/services/platform-verification-api/values.yaml -f platform/services/platform-verification-api/values-local.yaml --namespace gke-build-proj-local
```

Helm 4 lint does not run the chart's `fail` checks, so rendering is the real test. These two commands must fail.

Missing namespace:

```sh
helm template platform-verification-api platform/charts/service -f platform/services/platform-verification-api/values.yaml -f platform/services/platform-verification-api/values-staging.yaml
```

Expected error: `Target namespace mismatch! Derived namespace is 'gke-build-proj-staging', but release namespace is 'default'.`

Name longer than 63 characters:

```sh
helm template platform-verification-api platform/charts/service -f platform/services/platform-verification-api/values.yaml -f platform/services/platform-verification-api/values-staging.yaml --namespace gke-build-proj-staging --set serviceName=this-service-name-is-deliberately-long-for-testing
```

Expected error: `project, environment, and serviceName combine to "gke-build-proj-staging-this-service-name-is-deliberately-long-for-testing" (73 characters). K8s names allow at most 63.`

Neither lint nor rendering validates output against the Kubernetes API schema, so misspelled field names pass these manual commands silently. The [validation script](#validating-the-chart) adds that check.

## Chart inputs

`[platform/charts/service/values.schema.json](platform/charts/service/values.schema.json)` enforces these rules during lint and rendering. The combined name length and requests not above limits are checked by the chart's templates during rendering.


| Key                                                    | Required      | Rule                                                         |
| ------------------------------------------------------ | ------------- | ------------------------------------------------------------ |
| `project`                                              | Yes           | Lowercase letters, digits, and hyphens; starts with a letter |
| `environment`                                          | Yes           | `local` or `staging`                                         |
| `serviceName`                                          | Yes           | Same format as `project`                                     |
| `owner`                                                | Yes           | Kubernetes label value                                       |
| `image.repository`                                     | Yes           | Registry host and path, without tag or digest                |
| `image.digest`                                         | Yes           | `sha256:` followed by 64 lowercase hexadecimal characters    |
| `releaseVersion`                                       | Yes           | Quoted text; Kubernetes label value                          |
| `containerPort`                                        | Yes           | Integer from 1024 to 65535                                   |
| `probes.liveness.path`                                 | Yes           | Starts with `/`                                              |
| `probes.readiness.path`                                | Yes           | Starts with `/`                                              |
| `resources.requests.cpu`, `resources.limits.cpu`       | Yes           | Millicores, such as `100m`; requests not above limits        |
| `resources.requests.memory`, `resources.limits.memory` | Yes           | Mebibytes, such as `128Mi`; requests not above limits        |
| `replicaCount`                                         | No, default 2 | Integer from 2 to 3                                          |


`project`, `environment`, and `serviceName` together must produce a name of at most 63 characters. Service images must declare a numeric non-root user, because the chart requires non-root execution without setting a user ID.