# Infrastructure

GCP infrastructure for the platform in project `gke-build-proj`: a manual bootstrap, then one Terraform root. The design reference is [architecture.md](../architecture.md).

## Layout


| Path                                     | Contents                                                                          |
| ---------------------------------------- | --------------------------------------------------------------------------------- |
| `[bootstrap/](bootstrap/)`               | Manual bootstrap script and the retention rule for old Terraform state versions   |
| `[env/staging/](env/staging/)`           | The Terraform root: version constraints, backend, provider, and variables         |
| `modules/`                               | Terraform modules for the persistent and lab resources, added as they are written |
| `[tests/](tests/)`                       | Terraform validation script and its test input                                    |
| `[.trivyignore.yaml](.trivyignore.yaml)` | Accepted Trivy findings, each with a reason and an expiry date                    |
| `private/`                               | Saved Terraform plans. Local only and ignored by Git                              |




## How the infrastructure is organized

There is one Terraform root, `[env/staging/](env/staging/)`. Its state lives in the `staging` folder of the `gke-build-proj-staging-tfstate` bucket. Terraform runs with the owner's own credentials; a separate deployment account for the pipeline comes later.

Resources have two lifetimes:


| Lifetime   | Resources                                                                                                    | Created                                  | Removed                                           |
| ---------- | ------------------------------------------------------------------------------------------------------------ | ---------------------------------------- | ------------------------------------------------- |
| Persistent | Required APIs, the Artifact Registry image repository and its images, node service account | Always | Never by routine work; protected against deletion |
| Lab | VPC, subnet, Cloud Router and Cloud NAT, GKE cluster, node pool, and any other temporary resource | When a plan sets `lab_enabled` to `true` | When a plan sets `lab_enabled` to `false` |


The root currently manages no resources; the persistent and lab resources are planned. The budget and the billing export, including its dataset, are not managed by Terraform; see [Budget and billing export](#budget-and-billing-export).

## Sessions

A lab session lasts at most 24 hours from creation to removal. Always save a plan, review it, and apply that saved plan. A saved plan remembers the value of `lab_enabled`, so `apply` needs no `-var`.

`lab_enabled` has no default, so every plan must set it explicitly. A plan without it stops with `No value for required variable` instead of planning a teardown.

Plan paths are relative to `infra/env/staging/` because of `-chdir`, so `../../private/` is `infra/private/`.

To start a session, plan with the lab on:

```bash
terraform -chdir=infra/env/staging plan -var=lab_enabled=true -out=../../private/lab-on.tfplan
```

Review the plan, then apply it:

```bash
terraform -chdir=infra/env/staging apply ../../private/lab-on.tfplan
```

To end a session:

1. Stop Argo CD from recreating resources, then delete the Kubernetes objects that create cloud resources, such as Gateways, while the cluster still exists. Otherwise their load balancers are left behind.
2. Plan with the lab off, and check that only lab resources are removed:

   ```bash
   terraform -chdir=infra/env/staging plan -var=lab_enabled=false -out=../../private/lab-off.tfplan
   ```

3. Apply it:

   ```bash
   terraform -chdir=infra/env/staging apply ../../private/lab-off.tfplan
   ```

4. Check that no billable lab resources remain.

During a session, plan any other change with `-var=lab_enabled=true`, so the lab stays in place.

## Bootstrap

Terraform needs a few things before it can run: somewhere to store state, a small set of enabled APIs, and credentials. `[bootstrap/init_bootstrap.sh](bootstrap/init_bootstrap.sh)` creates them. Everything else belongs to Terraform, apart from the budget and the billing export, including its dataset.

### Prerequisites

- The project exists and is linked to a billing account.
- gcloud is signed in as the project owner.
- Application Default Credentials use `gke-build-proj` as the quota project. The script only warns about this; Terraform needs it.
- `infra/bootstrap/infra.env` exists. It is not in Git; create it with your preferred settings. These are the values used here:

  | Setting      | Value            |
  | ------------ | ---------------- |
  | `PROJECT_ID` | `gke-build-proj` |
  | `ENV`        | `staging`        |
  | `REGION`     | `us-east4`       |
  | `SERVICE`    | `platform`       |
  | `OWNER`      | `jd`             |




### What the script does

1. Checks the active account, the project, that billing is enabled, and the Application Default Credentials quota project.
2. Enables Service Usage, Cloud Resource Manager, IAM, IAM Service Account Credentials, and Cloud Storage.
3. If the Compute Engine API is on, lists the `default` network, its firewall rules, and any Editor grant to the Compute Engine default service account. It removes them only when run with `--apply-cleanup`.
4. Creates the two state buckets if they are missing, then reapplies every setting.
5. Prints the project details and each bucket's settings and IAM policy.

It is safe to rerun.

### State buckets


| Bucket                                    | Holds                                    | Access              |
| ----------------------------------------- | ---------------------------------------- | ------------------- |
| `gke-build-proj-staging-tfstate`          | State for `[env/staging/](env/staging/)` | Project owners only |
| `gke-build-proj-staging-identity-tfstate` | Nothing; kept for later use              | Project owners only |


Both buckets are in `us-east4` with the Standard storage class, uniform bucket-level access, public access prevention, object versioning, and 7-day soft delete. An old state version is deleted once it is more than 30 days old and at least 10 newer versions exist. The automatic grants to project viewers and editors are removed, so project Viewer does not grant read access to state.

### Running it

List only, without deleting anything:

```bash
bash infra/bootstrap/init_bootstrap.sh
```

After reviewing the Compute Engine defaults it lists, remove them:

```bash
bash infra/bootstrap/init_bootstrap.sh --apply-cleanup
```



## Budget and billing export

The budget and the billing export are set up by hand in the console, not by Terraform, so no billing account ID appears in this repository.

### Budget

First, check the billing account's currency under Billing, then Account management. Then create the budget under Billing, then Budgets & alerts:


| Setting                         | Value                                             |
| ------------------------------- | ------------------------------------------------- |
| Name                            | `gke-build-proj-staging-budget`                   |
| Time range                      | Monthly                                           |
| Projects                        | `gke-build-proj` only                             |
| Savings (credits and discounts) | None selected, so spend is counted before credits |
| Amount                          | 100 in the billing account's currency             |
| Alert thresholds                | 30%, 50%, and 99% of actual spend                 |
| Notifications                   | Email alerts to billing admins and users          |


At the start of each session, check that the budget still exists and belongs to the billing account the project is linked to. If the project is moved to another billing account, the old budget stops alerting without any warning.

The budget only sends alerts; it does not stop spending, and billing data arrives with a delay. Session length, resource limits, and ending each session on time are the real cost controls.

### Billing export

Turn this on before the first lab session, so cost data covers it.

1. In BigQuery, create a dataset named `gke_build_proj_staging_billing` in the `US` multi-region. A multi-region dataset receives data from the start of the previous month; a regional dataset only receives data from the day the export is turned on.
2. Under Billing, then Billing export, turn on **Detailed usage cost** export to that project and dataset. Google adds its export account as an owner of the dataset automatically.
3. Data starts arriving within a few hours.

## Validation

Run this before every commit:

```bash
bash infra/tests/validate-terraform.sh
```

It needs Terraform and Trivy, but no cloud credentials. It runs six checks:

1. Formatting: `terraform fmt` has nothing to change.
2. No `terraform.tfvars` or `*.auto.tfvars` anywhere under `infra/`. Every run uses committed values only.
3. Init without the backend, with a read-only lock file. Init fails if the providers no longer match the committed `.terraform.lock.hcl`.
4. Validate with `lab_enabled` set to `false`.
5. Validate with `lab_enabled` set to `true`.
6. Trivy misconfiguration scan of `infra/`, failing on HIGH and CRITICAL findings.

Exit codes: 0 when all checks pass, 1 when a check fails, 2 for a missing tool.

`[tests/lab-on.tfvars](tests/lab-on.tfvars)` sets `lab_enabled` to `true` for the Trivy scan only, so the resources behind the toggle are scanned with an explicit value rather than depending on how Trivy treats a variable with no default. Terraform never loads the file on its own.

To accept a Trivy finding, add an entry to `[.trivyignore.yaml](.trivyignore.yaml)` with:

- the check ID as Trivy prints it, for example `GCP-0027`
- the paths it applies to, relative to `infra/`
- a statement giving the reason
- an expiry date, after which the finding fails the check again



## Tool versions


| Tool             | Version        |
| ---------------- | -------------- |
| Terraform        | 1.16.4         |
| Google provider  | 8.5.0 (locked) |
| Trivy            | 0.74.0         |
| Google Cloud CLI | 587.0.0        |




## Status


| Work                                                                          | Status  |
| ----------------------------------------------------------------------------- | ------- |
| Bootstrap                                                                     | Done    |
| Terraform root and validation                                                 | Done    |
| Persistent resources: APIs, image repository, node service account | Planned |
| Budget, billing export dataset, and billing export (console) | Planned |
| Lab network and cluster                                                       | Planned |


