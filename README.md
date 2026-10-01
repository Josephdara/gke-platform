# GKE Application Platform

I'm building a reusable application deployment platform on GKE with Terraform, Kubernetes, Argo CD, Helm, Kyverno, Cloud Build, and Docker. When it is finished, you deploy a service through a reviewed configuration change and get secure defaults, health checks, and Git-based recovery. My design reference is [architecture.md](architecture.md).

It runs in my personal GCP project `gke-build-proj` as a temporary staging environment. I work to a $100 budget and remove the cluster within 24 hours of creating it. GCP resources are named `<environment>-<purpose>`, Kubernetes resources `<environment>-<service>`, and each environment has one namespace named `<environment>`; see [Project structure](architecture.md#project-structure).

## Where to start

| To | Read |
| --- | --- |
| Test the Python service, or build and run its image | [Applications README](apps/README.md) |
| Validate the Helm chart, or deploy it on Docker Desktop | [Platform README](platform/README.md) |
| Bootstrap GCP, apply Terraform, or run a lab session | [Infrastructure README](infra/README.md) |

## Repository layout

| Path | Contents |
| --- | --- |
| [`apps/platform-verification-api/`](apps/platform-verification-api/) | FastAPI service I use to verify deployment, health, configuration, and logging. See its [README](apps/platform-verification-api/README.md) |
| [`platform/charts/service/`](platform/charts/service/) | Shared Helm chart that deploys one HTTP service |
| [`platform/services/platform-verification-api/`](platform/services/platform-verification-api/) | Chart values for the API: `values.yaml` (shared) plus one environment file, `values-staging.yaml` or `values-local.yaml` |
| [`platform/namespaces/`](platform/namespaces/) | Local namespace manifest that enforces the Pod Security "restricted" profile |
| [`platform/tests/`](platform/tests/) | Chart validation script; its fixtures live in `platform/charts/service/tests/fixtures/` |
| [`infra/`](infra/) | GCP bootstrap, Terraform root and modules, and Terraform validation |
| [`architecture.md`](architecture.md) | Architecture and design decisions |
| `pipeline/` | Not created yet |

## Current status

| Build | Status |
| --- | --- |
| Architecture and design decisions | Done |
| Verification service and shared Helm chart | Done |
| GCP foundation: Terraform, GKE, Artifact Registry, IAM | Done |
| Image build pipeline: Cloud Build, recorded digests | Planned |
| GitOps deployment: Argo CD from Git | Planned |
| Identity and isolation, admission policies, validation suite, second service, observability and costs, acceptance tests, handoff | Planned |

What works today:

- **Service:** health routes, validated configuration, JSON logs with request IDs, and graceful shutdown. Its image runs as non-root user `10001` with a read-only root filesystem and no capabilities, and passes my Trivy gate for fixable HIGH and CRITICAL vulnerabilities.
- **Chart:** deploys one HTTP service with restricted pod security, digest-only images, probes, and rolling updates with zero unavailable pods. A values schema and template checks reject bad input before anything reaches a cluster. I deployed it on Docker Desktop Kubernetes into a namespace that enforces the "restricted" profile.
- **GCP:** Terraform manages the persistent resources, and a private GKE cluster that I create and remove in each lab session.

Planned changes to the service and chart:

- Consistency checks across rendered resources (selectors, port names, and resource references), and a recorded format for Trivy exceptions.
- A fix for the `KeyboardInterrupt` traceback after Ctrl+C.

The image repository and digest in `values-staging.yaml` are placeholders (`sample-registry.invalid`, all-zero digest) until the image pipeline publishes a real image.

## Tool versions

I built and tested the current state with these versions. The Terraform and Google Cloud versions are in the [Infrastructure README](infra/README.md#tool-versions).

| Tool | Version |
| --- | --- |
| Python | 3.14.6 |
| Helm | 4.3.0 |
| kubectl | 1.37.0 |
| Docker | 29.8.0 |
| Trivy | 0.74.0 |
| kubeconform | 0.8.0 |
