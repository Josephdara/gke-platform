# GKE Application Platform

A reusable application deployment platform on GKE, built with Terraform, Kubernetes, Argo CD, Helm, Kyverno, Cloud Build, and Docker. Developers deploy a service through a reviewed configuration change, with secure defaults, health checks, and Git-based recovery. The design reference is [architecture.md](architecture.md).

The platform runs in my personal GCP project `gke-build-proj`, as a temporary staging environment with a $100 budget and a 24-hour environment lifecycle. GCP resources are named `<environment>-<purpose>` and Kubernetes resources `<environment>-<service>`, in one namespace per environment named `<environment>`; see [architecture.md](architecture.md#project-structure).

## Repository layout


| Path                                                                                           | Contents                                                                                                                                  |
| ---------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `[apps/platform-verification-api/](apps/platform-verification-api/)`                           | FastAPI service used to verify deployment, health, configuration, and logging. See its [README](apps/platform-verification-api/README.md) |
| `[platform/charts/service/](platform/charts/service/)`                                         | Shared Helm chart that deploys one HTTP service                                                                                           |
| `[platform/services/platform-verification-api/](platform/services/platform-verification-api/)` | Chart values for the API: `values.yaml` (shared) plus one environment file, `values-staging.yaml` or `values-local.yaml`                  |
| `[platform/namespaces/](platform/namespaces/)`                                                 | Local namespace manifest that enforces the Pod Security "restricted" profile                                                              |
| `[platform/tests/](platform/tests/)`                                                           | Chart validation script; its fixtures live in `platform/charts/service/tests/fixtures/`                                                   |
| `[architecture.md](architecture.md)`                                                           | Architecture and design decisions                                                                                                         |
| `[infra/](infra/)`                                                                             | GCP infrastructure: bootstrap, Terraform root and modules, and validation. See its [README](infra/README.md)                              |
| `pipeline/`                                                                                    | TBD                                                                                                                                       |




## Current status


| Build                                                                                                                            | Status  |
| -------------------------------------------------------------------------------------------------------------------------------- | ------- |
| Architecture and design decisions                                                                                                | Done    |
| Verification service and shared Helm chart                                                                                       | Done    |
| GCP foundation: Terraform, GKE, Artifact Registry, IAM                                                                           | Done    |
| Image build pipeline: Cloud Build, recorded digests                                                                              | Planned |
| GitOps deployment: Argo CD from Git                                                                                              | Planned |
| Identity and isolation, admission policies, validation suite, second service, observability and costs, acceptance tests, handoff | Planned |


**Service and chart, done:**

- API with liveness (`/livez`), readiness (`/readyz`), and identity (`/`) routes, validated configuration, JSON logs with request IDs, graceful shutdown, and tests.
- Successful health-check requests log at DEBUG; a not-ready `/readyz` response logs at WARNING.
- Dockerfile with a digest-pinned base image and a numeric non-root user. pip is removed from the runtime image after dependencies are installed.
- Trivy policy gate passes: no fixable HIGH or CRITICAL vulnerabilities (Trivy 0.74.0, vulnerability database of 2026-09-28).
- Runtime security verified in Docker and in Kubernetes: user `10001`, read-only root filesystem, no effective capabilities, no privilege escalation, and seccomp filtering active.
- Local deployment on Docker Desktop Kubernetes from a local registry, into a namespace that enforces the Pod Security "restricted" profile. All checks in [Local deployment on Docker Desktop](platform/README.md#local-deployment-on-docker-desktop) passed on 2026-09-28, as run and reported by the owner.
- Shared chart with a ServiceAccount, ConfigMap, Deployment, and ClusterIP Service:
  - Names derived as `<environment>-<serviceName>`, failing above 63 characters.
  - Namespace derived as `<environment>`; rendering fails unless the release namespace matches.
  - Nine labels, including the required `project`, `environment`, `service`, and `owner`. Selectors use only `app.kubernetes.io/name` and `app.kubernetes.io/instance`.
  - Image referenced by digest only, with no tag.
  - Startup, liveness, and readiness probes on the named container port `app-http`.
  - Pod security: non-root, `RuntimeDefault` seccomp, read-only root filesystem, all capabilities dropped, no privilege escalation, no service account token.
  - Rolling updates with one surge pod and zero unavailable pods, and a 30-second termination grace period.
  - Values schema (`values.schema.json`) that rejects missing, unknown, and malformed inputs during lint and rendering; requests above limits fail during rendering.
- API values split into a shared `values.yaml` and one file per environment (`values-staging.yaml`, `values-local.yaml`). The shared file does not render on its own.
- [Validation script](platform/README.md#validating-the-chart) with 27 checks: application tests; lint, rendering, and strict Kubernetes schema validation for staging, local, and a second sample service that proves the chart renders another service without template changes; 15 invalid fixtures that must fail with the expected message; and wrong-namespace and shared-values-alone checks.

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




## Applications

Testing the Python service and building and running its container image are documented in the [applications README](apps/README.md):

- [Testing the Python service](apps/README.md#testing-the-python-service)
- [Building and running the container image](apps/README.md#building-and-running-the-container-image)



## Platform and Helm chart

The Helm chart, its validation, local deployment on Docker Desktop, and the chart's inputs are documented in the [platform README](platform/README.md):

- [Local deployment on Docker Desktop](platform/README.md#local-deployment-on-docker-desktop)
- [Validating the chart](platform/README.md#validating-the-chart)
- [Testing the Helm chart](platform/README.md#testing-the-helm-chart)
- [Chart inputs](platform/README.md#chart-inputs)

