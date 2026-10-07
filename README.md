# GKE Application Platform

I'm building a reusable application deployment platform on GKE with Terraform, Kubernetes, Argo CD, Helm, Kyverno, Cloud Build, and Docker. When it is finished, a developer deploys a service through a reviewed configuration change and gets secure defaults, health checks, and Git-based recovery. My design reference is [architecture.md](architecture.md).

It runs in my personal GCP project `gke-build-proj` as a temporary staging environment. I work to a $100 budget and remove the cluster within 24 hours of creating it. GCP resources are named `<environment>-<purpose>`, Kubernetes resources `<environment>-<service>`, and each environment has one namespace named `<environment>`; see [Project structure](architecture.md#project-structure).

## Where to start

| To | Read |
| --- | --- |
| Test the Python service, or build and run its image | [Applications README](apps/README.md) |
| Validate the Helm chart, or deploy it on Docker Desktop | [Platform README](platform/README.md) |
| Bootstrap GCP, apply Terraform, or run a lab session | [Infrastructure README](infra/README.md) |
| Publish an image, or choose which image staging runs | [Pipeline README](pipeline/README.md) |
| Run Argo CD, release, or roll back | [GitOps with Argo CD](platform/README.md#gitops-with-argo-cd) |

## Repository layout

| Path | Contents |
| --- | --- |
| [`apps/platform-verification-api/`](apps/platform-verification-api/) | FastAPI service I use to verify deployment, health, configuration, and logging. See its [README](apps/platform-verification-api/README.md) |
| [`platform/charts/service/`](platform/charts/service/) | Shared Helm chart that deploys one HTTP service |
| [`platform/services/platform-verification-api/`](platform/services/platform-verification-api/) | Chart values for the API: `values.yaml` (shared) plus one environment file, `values-staging.yaml` or `values-local.yaml` |
| [`platform/namespaces/`](platform/namespaces/) | Local namespace manifest that enforces the Pod Security "restricted" profile |
| [`platform/tests/`](platform/tests/) | Chart validation and live-check scripts, and the admission policy fixtures |
| [`platform/argocd/`](platform/argocd/) | Argo CD install overlay, the root project and Application, and the bootstrap script |
| [`platform/kyverno/`](platform/kyverno/) | Kyverno install overlay, with images from the mirror repository |
| [`platform/cluster/`](platform/cluster/) | What Argo CD manages from Git: the `staging` namespace and its guardrails, the Gateway, the admission policies, the projects, and the Applications |
| [`platform/evidence/`](platform/evidence/) | Reports from lab sessions; see the [index](platform/evidence/README.md) |
| [`infra/`](infra/) | GCP bootstrap, Terraform root and modules, and Terraform validation |
| [`architecture.md`](architecture.md) | Architecture and design decisions |
| [`pipeline/`](pipeline/) | Cloud Build configuration that tests, builds, scans, and publishes the API image. See its [README](pipeline/README.md) |

## Current status

| Build | Status |
| --- | --- |
| Architecture and design decisions | Done |
| Verification service and shared Helm chart | Done |
| GCP foundation: Terraform, GKE, Artifact Registry, IAM | Done |
| Image build pipeline: Cloud Build, recorded digests | Done |
| GitOps deployment: Argo CD from Git | Done |
| Identity, secrets, and namespace isolation | Done |
| Admission policies, chart 1.0.0, and HTTPS | Done |
| Validation suite: pull request CI and live checks | Done |
| Observability and costs, acceptance tests, handoff | Planned |

What works today:

- **Service:** health routes, validated configuration, JSON logs with request IDs, Prometheus request metrics on a separate port, and graceful shutdown. Its image runs as non-root user `10001` with a read-only root filesystem and no capabilities, and passes my Trivy gate for fixable MEDIUM, HIGH, and CRITICAL vulnerabilities.
- **Chart:** deploys one HTTP service with restricted pod security, digest-only images, probes, an autoscaler, a disruption budget, and rolling updates with zero unavailable pods. A values schema and template checks reject bad input before anything reaches a cluster. I deployed it on Docker Desktop Kubernetes into a namespace that enforces the "restricted" profile.
- **GCP:** Terraform manages the persistent resources, and a private GKE cluster that I create and remove in each lab session.
- **Pipeline:** Cloud Build tests, builds, and scans the API image on every pull request. Merges that change the API publish an image tagged with its commit, with provenance, a scan report, and an SBOM; a failed check means nothing is pushed.
- **GitOps:** Argo CD deploys staging from `main`. Releasing is a pull request that changes one digest, and rolling back is a Git revert that reuses the image already in the registry. In a lab session on 2026-10-03, a release took 1 minute 37 seconds and a rollback 1 minute 57 seconds from merge to healthy, with no unavailable pods; see the [evidence report](platform/evidence/2026-10-03-gitops.md).
- **Isolation:** each service reads its own Secret Manager secrets through its own Kubernetes service account, and a rotated value reaches it without a restart. The `staging` namespace denies all network traffic except DNS, caps resources with a quota and default limits, and gives developers read-only access. In a lab session on 2026-10-06, every unauthorized secret, Google API, network, and RBAC attempt was refused, and a new secret version reached every pod in 60 seconds; see the [evidence report](platform/evidence/2026-10-06-isolation.md).
- **Admission:** Kyverno checks every workload in `staging` against seven policies: approved registry, image digest, resources, labels, service account, Pod security, and a read-only root filesystem. Violations are rejected with a message naming the field and the fix, and the platform's own controller images come from my mirror repository. In a lab session on 2026-10-07, every failing fixture was denied while the running workloads passed; see the [evidence report](platform/evidence/2026-10-07-admission.md).
- **HTTPS:** during a lab session, the API answers at `https://api.staging.gke.josephdara.com/` through a GKE Gateway with a Google-managed certificate, and only the load balancer can reach its Pods.
- **Validation:** every pull request runs the app tests, the image scan, chart renders against the Kubernetes schemas, the policy fixtures, and the Terraform checks. `platform/tests/live-checks.sh` repeats the non-disruptive cluster checks in any session, and the [evidence index](platform/evidence/README.md) lists every session report.

Planned changes to the service and chart:

- Consistency checks across rendered resources (selectors, port names, and resource references), and a recorded format for Trivy exceptions.

`values-staging.yaml` points at an image the pipeline published. To choose a different one, see [Promoting an image to staging](pipeline/README.md#promoting-an-image-to-staging).

## Tool versions

I built and tested the current state with these versions. The Terraform and Google Cloud versions are in the [Infrastructure README](infra/README.md#tool-versions).

| Tool | Version |
| --- | --- |
| Python | 3.14.8 (image and CI) |
| Helm | 4.2.1 (the version bundled with Argo CD) |
| Argo CD | 3.5.3 (core install) |
| kubectl | 1.37.0 |
| Docker | 29.8.0 |
| Trivy | 0.74.0 |
| kubeconform | 0.8.0 |
| Kyverno CLI | 1.19.1 |
