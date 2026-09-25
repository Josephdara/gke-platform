# GKE Application Platform Architecture

## Platform goal

The platform provides a reusable application deployment environment on GKE, built with Terraform, Kubernetes, Argo CD, Helm, Kyverno, VPC networking, Cloud Build, and Docker. It applies production engineering practices within a temporary staging environment. Reviewed configuration changes define application deployments.

## Resource ownership

- **Terraform** owns the VPC and subnets, GKE cluster and node pools, Artifact Registry, Secret Manager resources and IAM, Google service accounts, workload identity permissions, billing controls, Cloud Build, and standalone DNS, IP, and certificate resources.
- **Argo CD** owns namespaces, scoped RBAC, Kubernetes service accounts (KSAs), application resources, SecretProviderClass, HPA/PDB, network policies, Gateway/HTTPRoute, and Kyverno.
- **Manual bootstrap** covers project and billing setup, the Terraform state bucket, initial Argo CD installation, and secret values. These dependencies are documented for reproducibility.

Terraform and Argo CD have separate resource ownership boundaries. GKE controllers own the cloud resources generated from Gateway objects, while the platform application owns cluster-scoped Kubernetes resources.

## Project structure

The project resides in the personal organization’s K8s folder. GCP resource names follow `<project>-<environment>-<purpose>`; Kubernetes resource names follow `<project>-<environment>-<service>`. Supported resources carry `project`, `environment`, `service`, and `owner` labels.

## Region and zones

The cluster and workers reside in `us-east4-b`, within `us-east4`. The zonal topology accepts zone-wide outages for this temporary project. [GKE availability choices](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/configuration-overview).

## Budget controls and project lifecycle

The budget is $100, with owner notifications at 30%, 50%, and 99%. The proposed accounting period is monthly, in the billing account’s currency. The thresholds correspond to spending review, suspension of additional experiments, and teardown before budget exhaustion. [Budget behavior](https://docs.cloud.google.com/billing/docs/how-to/budgets).

Each environment should have a maximum lifecycle of 24 hours from creation to teardown. Teardown verification covers remaining load balancers, disks, IP addresses, registry storage, and retained data.

## Repository model

A single repository contains `apps/`, `infra/`, `platform/`, and `pipeline/`. Cloud Build provides CI. Authorized branch pushes trigger validation, while merges into protected main publish staging deployment artifacts for Argo CD reconciliation.

## GKE cluster topology

The platform uses GKE Standard with DNS-based control-plane access, private nodes, the Secret Manager add-on, Cloud Logging, and Cloud Monitoring. The general-purpose node pool has two `e2-standard-2` nodes and scales to three. HPA, node auto-repair, and node auto-upgrade are enabled.

Component versions are pinned to compatible stable releases, and GKE follows the Regular release channel. The tested version set forms the compatibility baseline. Capacity validation includes controller overhead on the initial two-node pool.

## Networking

Terraform provisions a custom-mode VPC and subnet with node range `10.40.0.0/24`, pod range `10.41.0.0/20`, and service range `10.42.0.0/24`. Dataplane V2 provides network policy enforcement, and Private Google Access provides connectivity to Google services.

Application Services use ClusterIP. The first service is exposed through a global external managed Gateway, global static IP, DNS A record, and Certificate Manager certificate/map. Argo CD owns Gateway resources; Terraform owns the standalone IP, DNS, and certificate resources. [Gateway TLS support](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/gateway-security).

Workload connectivity includes DNS, approved service traffic, and identity or Google API access where required. Artifact Registry hosts OCI deployment bundles and mirrored controller images. Argo CD retrieves bundles from the registry; Cloud Build accesses GitHub outside the private cluster. Private Google Access provides no GitHub connectivity. [GKE networking guidance](https://docs.cloud.google.com/kubernetes-engine/docs/best-practices/networking).

## Terraform

Infrastructure is organized into modules with pinned stable Terraform/provider versions and a provider lock file. A restricted, versioned GCS bucket holds state independently of disposable infrastructure.

CI produces validation results and plans. Access to plan logs and artifacts is restricted because they may contain sensitive data. A manual Cloud Build apply trigger consumes the reviewed saved plan for the matching commit through a separate deployment identity.

## IAM and workload identity

Workload Identity Federation for GKE provides direct resource access with least-privilege permissions. Terraform grants each KSA principal access to specific Google Cloud resources.

Deployment remains owner-operated, without separate break-glass access. CI and workload identities have permissions distinct from the owner’s organization-level access.

## Secrets management

Secret Manager supplies mounted secrets through the managed GKE add-on. Each authorized KSA has `roles/secretmanager.secretAccessor` on the required secrets.

Mounted files refresh every two minutes, and applications reread updated values. Secret values are seeded manually and excluded from Git, images, and Terraform inputs/state. Application reload behavior completes the refresh path. [Managed add-on](https://docs.cloud.google.com/secret-manager/docs/secret-manager-managed-csi-component).

## Application services

Both services use Go’s standard HTTP library. The first returns service/version JSON and calls the second through `/backend`; the second returns a greeting and release identity. Each exposes `/livez` for process health and `/readyz` for local initialization and required configuration. Frontend liveness is independent of backend availability.

JSON logs contain timestamp, severity, service, environment, release, request ID, status, and duration. Secret values remain internal to the applications. Network isolation permits frontend-to-backend traffic and denies reverse or unrelated traffic. The second service shares the platform interface, with onboarding limited to service configuration and registration.

## Helm chart design

A shared chart defines Deployment, ClusterIP Service, KSA, ConfigMap, secret mounts, and probes. The extended chart includes HPA, PDB, NetworkPolicy, and optional HTTPRoute.

Required inputs are image digest, owner/cost labels, port, resource settings, and probe paths. Supported options include replica bounds, approved identity, secret references, and network dependencies. Schema validation rejects invalid types or ports, missing labels or digests, and inverted bounds. Arbitrary pod-spec overrides are outside the interface.

Security defaults include non-root execution, a read-only root filesystem, dropped capabilities, and disabled privilege escalation. Each application initially requests 100m CPU and 128Mi memory, with limits of 500m CPU and 256Mi memory. Replica bounds are two to three, CPU HPA targets 70%, and the PDB retains at least one available replica.

Rolling updates allow zero unavailable replicas and one surge replica. Probe defaults are five-second intervals, two-second timeouts, three consecutive failures, and a 30-second startup allowance. Graceful shutdown has a 30-second window. The capacity model includes peak application replicas, rollout surge, and controller overhead.

## Image build and software supply chain

Separate Artifact Registry repositories in `us-east4` hold images, charts, and deployment bundles. Build identities write their outputs, node identities pull images, and Argo CD reads bundles. Retention preserves current and recovery artifacts; unreferenced artifacts expire after seven days.

Branch CI covers service tests, chart/schema checks, policy fixtures, and vulnerability scanning. Build records include the source commit, image digest, provenance, and SBOM. Fixable high or critical vulnerabilities block release unless an owner-approved exception records a reason and expiry. Signing enforcement is deferred.

Configuration PRs select image and chart versions. Following merge, Cloud Build renders manifests into OCI bundles and records their immutable digests. Successful checks permit staging promotion. Promotions are serialized, and stale builds are ineligible. A Git revert produces a new publication of the restored configuration.

## GitOps and Argo CD

The initial Argo CD installation and registry authentication are manually bootstrapped at a pinned version. The platform application subsequently owns declarative settings. The documented bootstrap remains part of the recovery design.

The application model consists of one platform Application and one Application per service. Their sources are OCI bundles built from `platform/`. Each follows a staging tag with a recorded resolved digest. Service AppProjects are restricted to approved namespaces and the local cluster; cluster-wide permissions belong to the platform application. [Argo CD OCI sources](https://argo-cd.readthedocs.io/en/stable/user-guide/oci/).

Registry access is read-only. A dedicated workload identity renews short-lived registry tokens in an Argo CD repository credential, with RBAC restricted to that credential. Successful renewal across token expiry is an integration acceptance criterion. [Registry authentication](https://docs.cloud.google.com/artifact-registry/docs/docker/authentication).

Automated synchronization, self-healing, and service pruning are enabled. Destructive platform changes require owner review. Argo CD health and synchronization status expose drift. Recovery follows Git revert, bundle publication, and reconciliation.

## Admission policy

Kyverno provides admission control under platform-owner responsibility. Policies require approved registries, digest-pinned images, resource settings, ownership labels, approved KSAs, and restricted workload security. Host namespaces and paths, privileged containers, added capabilities, and privilege escalation are prohibited.

Policies enter enforcement after an audit phase and successful positive/negative fixtures. CI and live isolation tests validate namespace and network requirements. Exceptions are resource-scoped, owner-approved, justified, and limited to 24 hours. Rejection messages identify the failed field and required correction.

## Observability

Cloud Logging retains application logs for 30 days, excluding secrets and sensitive payloads. Cloud Monitoring supplies infrastructure visibility, and Managed Service for Prometheus supplies request rate, error, and latency metrics. The owner maintains dashboards.

Email alerts notify the owner of zero ready replicas for two minutes, error rates above 1% for five minutes under traffic, or p95 latency above 500ms for five minutes. A controlled failure validates notification delivery.

Active-test objectives are 99% successful requests and p95 latency below 500ms. Failed acceptance gates block promotion. These objectives apply to experiments rather than a monthly production SLO.

## Cost allocation and showback

The four required labels provide ownership and allocation context, with `service` as the cost grouping. Schema validation and Kyverno enforce workload labels; CI validates infrastructure labels. GKE cost allocation and detailed billing export provide usage and billing data.

Each experiment has a cost report separating direct service costs from shared platform, idle, and unallocated costs. Initial estimates are reconciled with billing exports as data becomes available.

## Validation and evidence

CI gates cover service tests, container scanning, Helm rendering/schema validation, Terraform validation/plans, and positive/negative Kyverno fixtures. Live checks cover deployment health, secret refresh, authorized and unauthorized IAM/RBAC access, and network isolation. Load, pod-failure, and node-drain exercises have separate execution paths.

Initial acceptance targets assume both services and warm nodes:


| Check                          | Target                                            |
| ------------------------------ | ------------------------------------------------- |
| Merge to healthy deployment    | Within 10 minutes, including CI                   |
| Git revert to healthy recovery | Within 10 minutes                                 |
| Baseline load                  | 20 requests/second for 10 minutes                 |
| Request quality                | Below 1% errors; p95 below 500ms                  |
| HPA                            | Scale within 3 minutes of sustained target breach |
| Pod replacement                | Ready within 2 minutes                            |
| Node drain                     | No total outage; same error/latency targets       |
| Alert delivery                 | Within 5 minutes after the condition qualifies    |


Reports reside under `platform/evidence/` and identify source/configuration revisions, artifact digests, versions, topology, load, timings, and expected versus actual outcomes.

## Developer onboarding

Onboarding prerequisites are repository access, documented tool versions, an approved image digest, service ownership, and verified permissions. CI provides configuration validation and feedback.

The developer interface consists of chart inputs and service registration submitted through a PR. The onboarding target is a healthy staging deployment within 30 minutes of satisfied prerequisites, without platform-source changes.

## Operations and recovery

The owner is responsible for health, spending, credentials, and component compatibility. Upgrade rehearsals and recorded version combinations support maintenance.

Incident diagnosis correlates release digest, Argo CD status, events, readiness, and logs. Persistent release-related health or acceptance failures are rollback conditions. Recovery authority remains with the owner.

Terraform, Git-derived artifacts, and documented bootstrap define cluster reconstruction. Protected state, secret versions, recovery images, and reports have independent retention. The applications are stateless. Initial recovery objectives are no loss of merged configuration and restoration within two hours, subject to access to retained dependencies.

## Architecture acceptance criteria

- Verified bootstrap identifiers, credentials, and DNS ownership.
- Demonstrated OCI publication, authentication renewal, and Git-based recovery.
- Validated capacity, isolation, policies, and acceptance targets.
- Verified billing notifications, teardown, and retained resources.

