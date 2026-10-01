# GKE Application Platform Architecture

## Platform goal

The platform provides a reusable application deployment environment on GKE, built with Terraform, Kubernetes, Argo CD, Helm, Kyverno, VPC networking, Cloud Build, and Docker. It applies production engineering practices within a temporary staging environment. Reviewed configuration changes define application deployments.

This document is the architecture source of truth. `plan.pdf` describes build sequencing; validation reports record which requirements have been demonstrated.

## Resource ownership

- **Terraform** owns the required APIs, the VPC and subnets, Cloud Router and Cloud NAT, GKE cluster and node pools, the Artifact Registry image repository, Secret Manager resources and IAM, Google service accounts, workload identity permissions, Cloud Build, and standalone DNS, IP, and certificate resources.
- **Argo CD** owns namespaces, scoped RBAC, Kubernetes service accounts (KSAs), application resources, SecretProviderClass, HPA/PDB, network policies, Gateway/HTTPRoute, and Kyverno.
- **Manual bootstrap** covers project and billing setup, one active Terraform state bucket and the APIs Terraform needs before it can run, the budget, the billing export dataset and its export configuration, Argo CD installation in each lab session, and secret values. These dependencies are documented for reproducibility.

Terraform and Argo CD have separate resource ownership boundaries. GKE controllers own the cloud resources generated from Gateway objects. Within Argo CD, the platform Application owns shared resources, including namespaces, platform RBAC, AppProjects, service Application definitions, Gateway resources, and admission policies. Each service Application owns its service chart resources. An individual Kubernetes resource has only one Application owner.

## Project structure

The project resides in the personal organization’s K8s folder. GCP resource names follow `<environment>-<purpose>`, such as `staging-vpc`, because every resource is already scoped to the project; Google service accounts follow `<environment>-<service>-sa`. Names that must be globally unique, such as the Terraform state buckets, keep the `<project>-<environment>-<purpose>` form. Resources created before this convention keep their original names, including the image repository `gke-build-proj-staging-images`. Kubernetes resource names follow `<environment>-<service>`, such as `staging-platform-verification-api`, in one namespace per environment named `<environment>`, such as `staging`. Supported resources carry `project`, `environment`, `service`, and `owner` labels; the project itself carries no labels, so cost grouping relies on resource labels.

## Region and zones

The cluster and workers reside in `us-east4-b`, within `us-east4`. The zonal topology accepts zone-wide outages for this temporary project. [GKE availability choices](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/configuration-overview).

## Budget controls and project lifecycle

The budget is $100, with owner notifications at 30%, 50%, and 99% of actual spend, counted before credits. The accounting period is monthly, in the billing account’s currency. The thresholds correspond to spending review, suspension of additional experiments, and an urgent spending alert. This alerts-only budget does not cap spending, and delayed usage reporting means the 99% alert cannot guarantee teardown before $100. Session duration, resource bounds, and owner-initiated teardown with spending headroom provide the cost controls. The budget and billing export configuration are managed manually in the console, so no billing account identifier appears in the repository; each lab session starts by confirming the budget still belongs to the project’s current billing account. [Budget behavior](https://docs.cloud.google.com/billing/docs/how-to/budgets).

Each lab session has a maximum lifecycle of 24 hours from creation to teardown. Persistent resources include the state bucket, enabled APIs, image repository and retained images, service accounts, Secret Manager secrets and retained versions, Cloud Build configuration and triggers, billing export dataset, DNS zone, certificate resources and their DNS authorization records, and retained logs and evidence. Lab resources include the VPC and subnets, Cloud Router and Cloud NAT, cluster and node pools, controller-created load balancers, reserved endpoint IP, and service DNS A record. The endpoint IP and A record are recreated with the lab. Persistent storage and any other retained-resource charges remain part of the monthly budget. Teardown verification covers remaining load balancers, disks, IP addresses, registry storage, and retained data.

## Repository model

A single public repository contains `apps/`, `infra/`, `platform/`, and `pipeline/`. Cloud Build provides CI. Authorized branch pushes trigger validation. Protected main requires PRs and successful applicable checks from the trusted CI integration. Merges affecting application builds publish checked container images; reviewed deployment configuration selects the image digest that Argo CD reconciles. The repository must exclude secrets, personal account identifiers, Terraform state, and sensitive plan or build artifacts. [Branch protection](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).

The delivery flow is application change, successful image build and scan, deployment configuration PR selecting the approved digest, Argo CD rendering from Git, and a healthy GKE deployment. A manual deployment configuration PR is sufficient. Chart, Application, AppProject, and pipeline changes receive platform-owner review because they can change deployment behavior or permissions.

## GKE cluster topology

The platform uses GKE Standard with DNS-based control-plane access, private nodes, the Secret Manager add-on, Cloud Logging, and Cloud Monitoring. The general-purpose node pool has two `e2-standard-2` nodes and scales to three. HPA, node auto-repair, and node auto-upgrade are enabled.

Tool and platform-controller versions are pinned to compatible stable releases. GKE follows the Regular release channel with managed automatic upgrades, so its version can change between experiments. The recorded tool, controller, and actual GKE versions form each experiment’s compatibility baseline. Capacity validation includes controller overhead on the initial two-node pool. [GKE release channels](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/release-channels).

## Networking

Terraform provisions a custom-mode VPC and subnet with node range `10.40.0.0/24`, pod range `10.41.0.0/20`, and service range `10.42.0.0/24`. Dataplane V2 provides network policy enforcement, and Private Google Access provides connectivity to Google services. A Cloud Router and Cloud NAT give the private nodes and pods outbound access, used by Argo CD to read the repository from GitHub; they belong to the lab lifecycle and its cost accounting. Cloud NAT allows outbound connections without public node IPs or unsolicited inbound traffic, but it does not filter destinations. [Cloud NAT](https://docs.cloud.google.com/nat/docs/overview)

Application Services use ClusterIP. The first service is exposed through a global external managed Gateway, global static IP, DNS A record, and Certificate Manager certificate/map. Certificate DNS authorization allows certificate resources to remain independent of the temporary endpoint IP. Argo CD owns Gateway resources; Terraform owns the standalone IP, DNS, and certificate resources. [Gateway TLS support](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/gateway-security), [certificate DNS authorization](https://docs.cloud.google.com/certificate-manager/docs/domain-authorization).

Workload connectivity includes DNS, approved service traffic, and identity or Google API access where required. Namespace isolation is part of the service interface. Restrictive internet egress is optional hardening and is not a prerequisite for the first Git-based deployment. When enabled, default-deny egress has explicit allowances for required DNS, Argo component communication, Kubernetes API access, GKE identity endpoints, and Google APIs. General outbound HTTPS is allowed for the Argo CD repository server to fetch Git sources.

Standard Kubernetes NetworkPolicy does not select destinations by domain name, so an internet HTTPS allowance limits which workloads connect, not the hosts they reach. GKE’s separate FQDN policy capability is outside the initial scope. Pod egress policies do not control node image pulls. Approved-registry admission rules govern application image sources; owner-managed controller images are mirrored into Artifact Registry, with Google-managed components governed separately. [GKE network-policy requirements and capabilities](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/network-policy).

## Terraform

Infrastructure is one Terraform root organized into modules, with pinned stable Terraform/provider versions and a provider lock file. A restricted, versioned GCS bucket holds its single state independently of the infrastructure. Every operational plan explicitly selects whether the lab is enabled through `lab_enabled`; omission is not teardown intent. Routine teardown applies a reviewed saved plan that disables the lab and removes only lab resources.

Persistent resources have explicit deletion safeguards appropriate to the resource and provider. State records ownership. Provider deletion policies recorded in state block Terraform-initiated deletion even if the resource configuration is removed; Terraform lifecycle protection depends on the configuration remaining present. Neither prevents deletion outside Terraform, and resource removals or replacements require review. A routine teardown plan is acceptable only when it preserves the designated persistent resources. [Terraform lifecycle protection](https://developer.hashicorp.com/terraform/language/meta-arguments/lifecycle).

General PR validation performs static Terraform checks without state access. Infrastructure plans run through a trusted workflow with separate planning permissions. Access to plan logs and artifacts is restricted because they may contain sensitive data. Until Terraform CI exists, the owner creates and applies reviewed saved plans with the owner’s credentials. A manual Cloud Build apply trigger will later consume the reviewed saved plan for the matching commit through a separate deployment identity.

## IAM and workload identity

Workload Identity Federation for GKE provides direct resource access with least-privilege permissions. Terraform grants each KSA principal access to specific Google Cloud resources.

Deployment remains owner-operated, without separate break-glass access. CI and workload identities have permissions distinct from the owner’s organization-level access.

Validation builds have only the permissions needed for checks and their outputs, without image-publication, infrastructure-apply, application-secret, or Terraform-state access. Trusted publication builds use a separate identity with image-write access scoped to the image repository and access needed for build evidence. Infrastructure planning and applying are trusted operations with separately scoped permissions. Build triggers select the intended service account explicitly. [Cloud Build identities](https://docs.cloud.google.com/build/docs/securing-builds/configure-user-specified-service-accounts).

Node identities have Artifact Registry Reader access scoped to the image repository and compatible node access scopes. Application KSA permissions govern application API calls independently of node image pulls. Argo CD reads the public Git repository without credentials. [GKE image access](https://docs.cloud.google.com/artifact-registry/docs/integrate-gke).

## Secrets management

Secret Manager supplies mounted secrets through the managed GKE add-on. Each authorized KSA has `roles/secretmanager.secretAccessor` on the required secrets.

Automatic rotation is explicitly enabled on a supported GKE version with a two-minute rotation interval. Secret references intended to rotate resolve updated versions, and applications reread changed mounted files. Live validation measures the complete path from a new secret version to application use; the configured interval is not a guaranteed application-observation deadline. Secret values are seeded manually and excluded from Git, images, and Terraform inputs/state. [Managed add-on and rotation](https://docs.cloud.google.com/secret-manager/docs/secret-manager-managed-csi-component).

## Application services

The first service, `platform-verification-api`, uses Python with FastAPI and Uvicorn. It returns service/version JSON and exposes `/livez` for process health and `/readyz` for local initialization and required configuration. A later `/backend` integration will call the second service for a greeting and release identity. The second service also exposes health endpoints; its implementation is deferred. API liveness is independent of backend availability.

JSON logs contain timestamp, severity, service, environment, release, request ID, status, and duration. Secret values remain internal to the applications. Network isolation permits frontend-to-backend traffic and denies reverse or unrelated traffic. The second service shares the platform interface, with onboarding limited to service configuration and registration.

## Helm chart design

A shared chart defines Deployment, ClusterIP Service, KSA, ConfigMap, secret mounts, and probes. The extended chart includes HPA, PDB, NetworkPolicy, and optional HTTPRoute.

Required inputs are image digest, owner/cost labels, port, resource settings, and probe paths. Supported options include replica bounds, approved identity, secret references, and network dependencies. Schema and chart validation reject invalid types or ports, missing labels or digests, and inverted bounds. Arbitrary pod-spec overrides are outside the interface.

Security defaults include non-root execution, a read-only root filesystem, dropped capabilities, and disabled privilege escalation. Each application initially requests 100m CPU and 128Mi memory, with limits of 500m CPU and 256Mi memory. Replica bounds are two to three, CPU HPA targets 70%, and the PDB retains at least one available replica.

When HPA is enabled, it owns the live replica count within the declared bounds; the rendered Deployment does not specify a competing fixed count for Argo CD to restore. Before HPA is introduced, the chart supplies the initial replica count. [Argo CD and HPA ownership](https://argo-cd.readthedocs.io/en/stable/user-guide/best_practices/).

Rolling updates allow zero unavailable replicas and one surge replica. Probe defaults are five-second intervals, two-second timeouts, three consecutive failures, and a 30-second startup allowance. Graceful shutdown has a 30-second window. The capacity model includes peak application replicas, rollout surge, and controller overhead.

Argo CD renders the chart from Git. Local validation and CI use one documented Helm baseline matching the pinned Argo CD release. Render checks use the reviewed Git revision, matching values files and precedence, release name, namespace, fixed dependency versions, and relevant target Kubernetes capabilities. Matching Helm versions alone does not prove render equivalence or live deployment success. [Argo CD Helm inputs](https://argo-cd.readthedocs.io/en/stable/user-guide/helm/), [Application rendering options](https://argo-cd.readthedocs.io/en/stable/user-guide/application-specification/).

## Image build and software supply chain

An Artifact Registry repository in `us-east4` holds container images. Build identities publish images and node identities pull them. Retention preserves deployed and designated recovery images, which are marked explicitly; other images become eligible for cleanup after seven days. Cleanup policies stay in dry-run mode until that marking exists and retention behavior has been verified. [Artifact Registry cleanup policies](https://docs.cloud.google.com/artifact-registry/docs/repositories/cleanup-policy).

Branch CI covers service tests, chart/schema checks, policy fixtures, and vulnerability scanning. Build records include the source commit, image digest, provenance, and SBOM. Fixable high or critical vulnerabilities block release unless an owner-approved exception records a reason and expiry. Signing enforcement is deferred.

Configuration PRs select existing image digests with successful build and required scan evidence tied to the source commit and exact digest. Required deployment checks verify that evidence and validate the resulting configuration. Chart changes are reviewed as deployment changes because they affect every service using the chart. Image-build triggers cover application source, Dockerfiles, dependencies, and build configuration. Deployment-only changes receive their applicable validation without rebuilding an image. [Cloud Build trigger filtering](https://docs.cloud.google.com/build/docs/automating-builds/create-manage-triggers).

## GitOps and Argo CD

Argo CD is installed at a pinned version by a documented bootstrap at the start of each lab session, because the cluster is recreated every session. The platform application subsequently owns declarative settings. The documented bootstrap remains part of the recovery design.

The application model consists of one platform Application and one Application per service. All use this Git repository on protected main. The platform Application reads a dedicated platform-manifest source separate from the service chart. Each service Application reads the shared chart in `platform/charts/service/` and its shared and staging values from `platform/services/`, with chart and values resolved from the same Git revision. Platform namespaces, CRDs, and other required prerequisites are ready before dependent service resources synchronize. [Application specification](https://argo-cd.readthedocs.io/en/stable/user-guide/application-specification/).

Argo CD renders the chart itself and polls the public repository without read credentials, so no public webhook endpoint is needed. Service AppProjects allow only the approved repository, service namespaces, local cluster, and required resource kinds. They exclude the Argo CD namespace and cluster-scoped resource management. The platform Application has the permissions required for shared and cluster-scoped resources. [AppProject restrictions](https://argo-cd.readthedocs.io/en/stable/user-guide/projects/).

Argo CD reconciles the latest desired configuration from protected main; intermediate commits may be skipped. Applications reconcile independently, so a repository revision does not imply an atomic rollout across services. Automated synchronization, self-healing, service pruning, and bounded synchronization retries are enabled. Destructive platform changes require owner review. Argo CD synchronization and health status distinguish configuration drift from workload health; neither guarantees a successful release. Failed releases require correction or Git revert to retained configuration and image digests, without rebuilding the image. [Automated synchronization](https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/).

Lab teardown follows the controller cleanup and persistent-resource requirements in Operations and recovery.

## Admission policy

Kyverno provides admission control under platform-owner responsibility. Application policies select the designated application namespaces and workload kinds. They require approved registries, digest-pinned images, resource settings, ownership labels, approved KSAs, and restricted workload security. Host namespaces and paths, privileged containers, added capabilities, and privilege escalation are prohibited for those application workloads. Platform controllers and Google-managed components have separately reviewed policy coverage and required permissions. [Kyverno policy scope](https://kyverno.io/docs/policy-types/cluster-policy/match-exclude/).

Policies enter enforcement after an audit phase and successful positive/negative fixtures. CI and live isolation tests validate namespace and network requirements. Exceptions are resource-scoped, owner-approved, justified, and limited to 24 hours. Rejection messages identify the failed field and required correction.

## Observability

Cloud Logging retains application logs for 30 days, excluding secrets and sensitive payloads. Cloud Monitoring supplies infrastructure visibility, and Managed Service for Prometheus supplies request rate, error, and latency metrics. The owner maintains dashboards.

Email alerts notify the owner of zero ready replicas for two minutes, error rates above 1% for five minutes under traffic, or p95 latency above 500ms for five minutes. A controlled failure validates notification delivery.

Active-test objectives are 99% successful requests and p95 latency below 500ms. Failed live acceptance checks place further releases on an owner-enforced hold until correction or recovery is verified. This hold is distinct from the automated checks required before a PR can merge. These objectives apply to experiments rather than a monthly production SLO.

## Cost allocation and showback

The four required labels provide ownership and allocation context, with `service` as the cost grouping. Schema validation and Kyverno enforce workload labels; CI validates infrastructure labels. GKE cost allocation and detailed billing export provide usage and billing data.

Each experiment has a cost report separating direct service costs from shared platform, idle, and unallocated costs. Initial estimates are reconciled with billing exports as data becomes available.

## Validation and evidence

Required PR checks cover the applicable service tests, container scanning, approved image evidence, Helm rendering/schema validation with the documented Helm baseline, static Terraform validation, and positive/negative Kyverno fixtures. Infrastructure plans use the separate trusted workflow. Live checks cover deployment health, the running image digest matching approved configuration, secret refresh, authorized and unauthorized IAM/RBAC access, and namespace isolation. Restrictive internet-egress checks apply when that option is enabled. Retention checks confirm that deployed and recovery images remain available. Load, pod-failure, and node-drain exercises have separate execution paths.

Initial acceptance targets assume both services and warm nodes:

| Check                                             | Target                                           |
| ------------------------------------------------- | ------------------------------------------------ |
| Deployment configuration merge to healthy service | Within 10 minutes                                |
| Git revert merge to healthy recovery              | Within 10 minutes                                |
| Baseline load                                     | 20 requests/second for 10 minutes                 |
| Request quality                                   | Below 1% errors; p95 below 500ms                  |
| HPA                                               | Scale within 3 minutes of sustained target breach |
| Pod replacement                                   | Ready within 2 minutes                           |
| Node drain                                        | No total outage; same error/latency targets       |
| Alert delivery                                    | Within 5 minutes after the condition qualifies   |

Image-build and scan duration, pre-merge validation, and time awaiting a deployment PR are recorded separately from deployment reconciliation. Reports reside under `platform/evidence/` and identify source/configuration revisions, artifact digests, actual tool/controller/GKE versions, topology, load, timings, and expected versus actual outcomes. Published reports exclude secrets and sensitive plan or build content.

## Developer onboarding

Onboarding prerequisites are repository access, documented tool versions, an approved image digest, service ownership, and verified permissions. CI provides configuration validation and feedback.

The developer interface consists of chart inputs and service registration submitted through a PR. The onboarding target is a healthy staging deployment within 30 minutes of satisfied prerequisites, without platform-source changes.

## Operations and recovery

The owner is responsible for health, spending, credentials, and component compatibility. Upgrade rehearsals and recorded version combinations support maintenance.

Incident diagnosis correlates release digest, Argo CD status, events, readiness, and logs. Persistent release-related health or acceptance failures are rollback conditions. Recovery authority remains with the owner.

Lab teardown prevents Argo CD from recreating resources being removed. Kubernetes deletion targets the owning Gateway and related resources, while the cluster and controllers required for finalization remain available. Controller-created load balancers and associated resources must finish cleanup before Terraform removes the cluster, network, and remaining lab resources. Cleanup verification distinguishes expected persistent resources from leaked lab resources. [GKE Gateway cleanup risks](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/deploying-gateways).

Terraform, the Git repository, retained images, and documented bootstrap define cluster reconstruction. Protected state, secret versions, recovery images, and reports have independent retention. The applications are stateless. Initial recovery objectives are no loss of merged configuration and restoration within two hours, subject to access to retained dependencies.

## Architecture acceptance criteria

- Verified bootstrap identifiers, credentials, and DNS ownership.
- Demonstrated Git-based deployment and revert recovery using approved, retained image digests.
- Validated required permissions, capacity, namespace isolation, policies, and acceptance targets; restrictive internet-egress checks pass when that option is enabled.
- Verified billing notifications and teardown that removes lab resources while preserving designated persistent resources.
