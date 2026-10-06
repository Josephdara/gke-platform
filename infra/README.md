# Infrastructure

This is how I set up and run the GCP side of the platform in project `gke-build-proj`: a bootstrap script that runs once, then one Terraform root, planned and applied for every change. My design reference is [architecture.md](../architecture.md). Run every command on this page from the repository root.

## Layout

| Path | Contents |
| --- | --- |
| [`bootstrap/`](bootstrap/) | Bootstrap script and the retention rule for old Terraform state versions |
| [`env/staging/`](env/staging/) | The Terraform root: version constraints, backend, provider, variables, and module calls |
| [`modules/foundation/`](modules/foundation/) | Required APIs, including Cloud Build and Container Analysis, and the Artifact Registry image and mirror repositories |
| [`modules/identity/`](modules/identity/) | The GKE node and Cloud Build service accounts and their project roles |
| [`modules/pipeline/`](modules/pipeline/) | Build evidence bucket, Cloud Build repository link, and the two build triggers |
| [`modules/secrets/`](modules/secrets/) | Secret Manager secrets, each service's read grants, and Data Access audit logging for Secret Manager |
| [`modules/edge/`](modules/edge/) | DNS zone, Certificate Manager certificate and map, and the lab's static IP and A record |
| [`modules/network/`](modules/network/) | Lab network: VPC, subnet, Cloud Router, and Cloud NAT |
| [`modules/gke/`](modules/gke/) | Lab GKE cluster and node pool |
| [`tests/`](tests/) | Terraform validation script and its test input |
| [`.trivyignore.yaml`](.trivyignore.yaml) | Accepted Trivy findings, each with a reason and an expiry date |
| `private/` | Saved Terraform plans. Git ignores it |

## What Terraform manages

I use one Terraform root, [`env/staging/`](env/staging/). Its state lives under the `staging` prefix of the `gke-build-proj-staging-tfstate` bucket. I run Terraform with my own project owner credentials. To run it yourself, you need the same access. Terraform CI, with its own deployment account, comes with the validation suite.

Persistent resources stay between sessions and are protected against deletion. Lab resources exist only during a session: a plan with `lab_enabled=true` creates them, and a plan with `lab_enabled=false` removes them.

| Resource | Name | Lifetime |
| --- | --- | --- |
| Required APIs | Artifact Registry, Compute Engine, Kubernetes Engine, Logging, Monitoring, Secret Manager, Cloud Build, Container Analysis, Cloud DNS, Certificate Manager | Persistent |
| Image repository | `gke-build-proj-staging-images` (named before the `<environment>-<purpose>` convention) | Persistent |
| Mirror repository | `staging-mirror`: controller images copied unchanged from upstream, with no cleanup policy, protected against deletion | Persistent |
| Node service account | `staging-nodes-sa`, with read access to the image and mirror repositories | Persistent |
| Build service accounts | `staging-build-validate-sa`, which can only write logs; `staging-build-publish-sa`, which can also write to the image repository, and create and list objects in the evidence bucket but not read, overwrite, or delete them | Persistent |
| Build evidence bucket | `gke-build-proj-staging-build-evidence`: scan reports and SBOMs, deleted after 90 days, protected against deletion | Persistent |
| Secrets | `staging-platform-verification-api-demo`, readable only by the API's Kubernetes service account, and `staging-forbidden-demo`, with no grants. Values are added by hand, never through Terraform. Data Access audit logs record every read | Persistent |
| Build triggers | Repository link `gke-platform`, and triggers `staging-pr-validate` and `staging-main-publish`; see the [pipeline README](../pipeline/README.md) | Persistent |
| DNS and certificate | Zone `staging-dns` for `gke.josephdara.com`, with DNSSEC; certificate `staging-api-cert` for `api.staging.gke.josephdara.com`, validated through DNS authorization `staging-api-dns-auth`; certificate map `staging-cert-map`. All protected against deletion | Persistent |
| Network | `staging-vpc`; subnet `staging-nodes-subnet` (10.40.0.0/24, pods 10.41.0.0/20, services 10.42.0.0/24) with Private Google Access | Lab |
| Outbound access | `staging-router` and `staging-nat` | Lab |
| Cluster | `staging-super-cluster`: zonal in us-east4-b, Regular channel from 1.36, private nodes, DNS endpoint only, NodeLocal DNSCache, no RBAC bindings to `system:authenticated` or `system:unauthenticated` | Lab |
| Node pool | `staging-super-pool`: 2 to 3 e2-standard-2 nodes, 30 GB pd-balanced disks | Lab |
| Gateway address | Global static IP `staging-gateway-ip`, and the A record `api.staging.gke.josephdara.com` pointing to it | Lab |

Terraform does not manage the budget or the billing export; both are set up by hand in the console. See [Budget and billing export](#budget-and-billing-export).

## Sessions

A session lasts at most 24 hours from creation to removal. For every change, save a plan, review it, and apply that saved plan. The saved plan remembers `lab_enabled`, so `apply` needs no `-var`.

Always pass `-var=lab_enabled=…` on every plan. The variable defaults to `false`, so a plan without it proposes removing the lab. If you see a plan like that during a session, discard it. To plan any other change during a session, use `-var=lab_enabled=true` so the lab stays in place.

Because of `-chdir`, plan paths are relative to `infra/env/staging/`, so `../../private/` is `infra/private/`.

### Start a session

1. Plan with the lab on, and review the plan:

   ```bash
   terraform -chdir=infra/env/staging plan -var=lab_enabled=true -out=../../private/lab-on.tfplan
   ```

2. Apply the saved plan:

   ```bash
   terraform -chdir=infra/env/staging apply ../../private/lab-on.tfplan
   ```

3. Get credentials through the DNS endpoint. The cluster has no IP endpoints:

   ```bash
   gcloud container clusters get-credentials staging-super-cluster --zone=us-east4-b --project=gke-build-proj --dns-endpoint
   ```

4. Install Argo CD and hand the cluster over to Git. Run this from an up-to-date `main`, because it applies `platform/argocd/` from your checkout:

   ```bash
   platform/argocd/bootstrap.sh
   ```

   It ends with `PASS  running image matches Git` once both Applications are Synced and Healthy. See [GitOps with Argo CD](../platform/README.md#gitops-with-argo-cd).

Pass `--context gke_gke-build-proj_us-east4-b_staging-super-cluster` on every `kubectl` and `helm` command. Your kubectl must be within one minor version of the cluster (1.36).

### End a session

1. Stop Argo CD from recreating resources. Turn off automated sync on the root Application first, because it would otherwise restore the service Application's automation, then on the service Application:

   ```bash
   kubectl --context gke_gke-build-proj_us-east4-b_staging-super-cluster -n argocd patch applications.argoproj.io staging-platform --type merge -p '{"spec":{"syncPolicy":{"automated":null}}}'
   ```

   ```bash
   kubectl --context gke_gke-build-proj_us-east4-b_staging-super-cluster -n argocd patch applications.argoproj.io staging-platform-verification-api --type merge -p '{"spec":{"syncPolicy":{"automated":null}}}'
   ```

   Then delete any Kubernetes objects that create cloud resources, such as Gateways, while the cluster still exists. Otherwise their load balancers are left behind. Both of these must print nothing:

   ```bash
   kubectl --context gke_gke-build-proj_us-east4-b_staging-super-cluster get svc -A --field-selector spec.type=LoadBalancer --no-headers
   ```

   ```bash
   kubectl --context gke_gke-build-proj_us-east4-b_staging-super-cluster get gateway -A --no-headers
   ```

2. Plan with the lab off, and check that it removes only lab resources:

   ```bash
   terraform -chdir=infra/env/staging plan -var=lab_enabled=false -out=../../private/lab-off.tfplan
   ```

3. Apply the saved plan:

   ```bash
   terraform -chdir=infra/env/staging apply ../../private/lab-off.tfplan
   ```

4. Check that no billable lab resources remain. Every list must be empty, except `compute networks` and `compute firewall-rules`, which must show nothing from `staging-vpc`. The `${=r}` splits each entry into words in zsh; in bash, use `$r`:

   ```bash
   for r in "container clusters" "compute instances" "compute disks" "compute addresses" "compute forwarding-rules" "compute network-endpoint-groups" "compute routers" "compute networks" "compute firewall-rules"; do echo "== $r"; gcloud ${=r} list --project=gke-build-proj --format="value(name)"; done
   ```

   Then confirm Terraform agrees. Expect `No changes` and `exit=0`:

   ```bash
   terraform -chdir=infra/env/staging plan -var=lab_enabled=false -detailed-exitcode; echo "exit=$?"
   ```

## Bootstrap

Before Terraform can run, it needs somewhere to store state, a few enabled APIs, and credentials. [`bootstrap/init_bootstrap.sh`](bootstrap/init_bootstrap.sh) creates the first two and checks the third. Run it once for a new project; it is safe to rerun.

### Before you run it

- The project exists and is linked to a billing account.
- gcloud is signed in as a project owner.
- Your Application Default Credentials use `gke-build-proj` as the quota project. The script only warns about this, but Terraform needs it.
- `infra/bootstrap/infra.env` exists. Git ignores it, so create it yourself. These are my values:

  | Setting | Value |
  | --- | --- |
  | `PROJECT_ID` | `gke-build-proj` |
  | `ENV` | `staging` |
  | `REGION` | `us-east4` |
  | `SERVICE` | `platform` |
  | `OWNER` | `jd` |

### What the script does

1. Checks the active account, the project, that billing is enabled, and the Application Default Credentials quota project.
2. Enables Service Usage, Cloud Resource Manager, IAM, IAM Service Account Credentials, and Cloud Storage.
3. If the Compute Engine API is on, lists the `default` network, its firewall rules, and any Editor grant to the Compute Engine default service account. It removes them only when run with `--apply-cleanup`.
4. Creates the two state buckets if they are missing, then reapplies every setting.
5. Prints the project details and each bucket's settings and IAM policy.

### State buckets

| Bucket | Holds | Access |
| --- | --- | --- |
| `gke-build-proj-staging-tfstate` | State for [`env/staging/`](env/staging/) | Project owners only |
| `gke-build-proj-staging-identity-tfstate` | Nothing; kept for later use | Project owners only |

Both buckets are in `us-east4` with the Standard storage class, uniform bucket-level access, public access prevention, object versioning, and 7-day soft delete. An old state version is deleted once it is more than 30 days old and at least 10 newer versions exist. The script removes the automatic grants to project viewers and editors, so project Viewer cannot read state.

### Running it

Run it first in list-only mode; it deletes nothing:

```bash
bash infra/bootstrap/init_bootstrap.sh
```

Review the Compute Engine defaults it lists, then remove them:

```bash
bash infra/bootstrap/init_bootstrap.sh --apply-cleanup
```

### Cloud Build GitHub connection

Terraform links the repository and creates the triggers, but the connection to GitHub is a manual step, so no GitHub token ever passes through Terraform. Create it once, before the first plan that includes the pipeline module:

1. In the console, open Cloud Build, then Repositories (2nd gen), and create a host connection to GitHub in `us-east4` named `staging-github`.
2. When GitHub asks, install the Cloud Build app on this repository only, not on all repositories.
3. Do not link the repository in the console. Terraform does that.

Google stores the connection's token in Secret Manager. Never read it or copy it anywhere.

## Budget and billing export

Set these up by hand in the console. I keep them out of Terraform so no billing account ID appears in this public repository.

### Budget

Check the billing account's currency under Billing, then Account management. Then create the budget under Billing, then Budgets & alerts:

| Setting | Value |
| --- | --- |
| Name | `gke-build-proj-staging-budget` |
| Time range | Monthly |
| Projects | `gke-build-proj` only |
| Savings (credits and discounts) | None selected, so spend is counted before credits |
| Amount | 100 in the billing account's currency |
| Alert thresholds | 30%, 50%, and 99% of actual spend |
| Notifications | Email alerts to billing admins and users |

At the start of each session, check that the budget still exists and belongs to the billing account the project is linked to. If the project moves to another billing account, the old budget stops alerting without any warning.

The budget only sends alerts. It does not stop spending, and billing data arrives with a delay, so the real cost controls are session length, resource limits, and ending each session on time.

### Billing export

Turn this on before your first session, so cost data covers it.

1. In BigQuery, create a dataset named `gke_build_proj_staging_billing` in the `US` multi-region. A multi-region dataset receives data from the start of the previous month; a regional dataset only receives data from the day the export is turned on.
2. Under Billing, then Billing export, turn on **Detailed usage cost** export to that project and dataset. Google adds its export account as an owner of the dataset automatically.
3. Data starts arriving within a few hours.

## Validation

Run this before every commit. It needs Terraform and Trivy, but no cloud credentials:

```bash
bash infra/tests/validate-terraform.sh
```

It runs six checks:

1. Formatting: `terraform fmt` has nothing to change.
2. No `terraform.tfvars` or `*.auto.tfvars` anywhere under `infra/`, so every run uses committed values only.
3. Init without the backend and with a read-only lock file. Init fails if the providers no longer match the committed `.terraform.lock.hcl`.
4. Validate with `lab_enabled` set to `false`.
5. Validate with `lab_enabled` set to `true`.
6. Trivy misconfiguration scan of `infra/`, failing on MEDIUM, HIGH, and CRITICAL findings.

Exit codes: 0 when all checks pass, 1 when a check fails, 2 for a missing tool.

[`tests/lab-on.tfvars`](tests/lab-on.tfvars) sets `lab_enabled` to `true` for the Trivy scan only, so Trivy scans the resources behind the toggle with an explicit value. Terraform never loads the file on its own.

To accept a Trivy finding, add an entry to [`.trivyignore.yaml`](.trivyignore.yaml) with:

- the check ID as Trivy prints it, for example `GCP-0027`
- the paths it applies to, relative to `infra/`
- a statement giving the reason
- an expiry date, after which the finding fails the check again

## Tool versions

I used these versions:

| Tool | Version |
| --- | --- |
| Terraform | 1.16.4 |
| Google provider | 8.5.0 (locked) |
| Trivy | 0.74.0 |
| Google Cloud CLI | 587.0.0 |

## Status

| Work | Status |
| --- | --- |
| Bootstrap | Done |
| Terraform root and validation | Done |
| Persistent resources: APIs, image repository, node service account | Done |
| Image pipeline resources and GitHub connection | Done |
| Budget, billing export dataset, and billing export (console) | Done |
| Lab network and cluster | Created and deleted in each session |
| Argo CD on the lab cluster | Verified in session 3; see the [evidence report](../platform/evidence/2026-10-03-gitops.md) |
| Workload secrets, per-service grants, and Secret Manager audit logs | Verified in session 4; see the [evidence report](../platform/evidence/2026-10-06-isolation.md) |
