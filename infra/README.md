# Infrastructure

GCP infrastructure for the platform in project `gke-build-proj`: a manual bootstrap, then Terraform. The design reference is [architecture.md](../architecture.md).

## Layout


| Path                                           | Contents                                                                                                                                   |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `[init_bootstrap.sh](init_bootstrap.sh)`       | Manual bootstrap: the APIs Terraform needs first, project labels, Terraform state buckets, and optional cleanup of Compute Engine defaults |
| `[infra.env](infra.env)`                       | Settings the bootstrap reads: project, environment, region, and label values                                                               |
| `[state-lifecycle.json](state-lifecycle.json)` | Retention rule for old versions of Terraform state                                                                                         |




## How the infrastructure is organized

Terraform is split into three roots by who applies them and how long their resources live. The roots are planned and not written yet.


| Root       | Applied by                  | Owns                                                          | Lifetime                              |
| ---------- | --------------------------- | ------------------------------------------------------------- | ------------------------------------- |
| identity   | The owner's own credentials | Deployment and node service accounts and their grants         | Persistent                            |
| foundation | Deployment service account  | APIs, Artifact Registry repositories, billing dataset, budget | Persistent                            |
| staging    | Deployment service account  | VPC, subnet, GKE cluster, node pool                           | Destroyed within 24 hours of creation |


Apply order is identity, then foundation, then staging. Only staging is ever destroyed.

## Bootstrap

Terraform needs a few things before it can run: somewhere to store state, a small set of enabled APIs, and credentials. `[init_bootstrap.sh](init_bootstrap.sh)` creates them. Everything else belongs to Terraform.

### Prerequisites

- The project exists and is linked to a billing account.
- gcloud is signed in as the project owner.
- Application Default Credentials use `gke-build-proj` as the quota project. The script only warns about this; Terraform needs it.



### What the script does

1. Checks the active account, the project, that billing is enabled, and the Application Default Credentials quota project.
2. Enables Service Usage, Cloud Resource Manager, IAM, IAM Service Account Credentials, and Cloud Storage.
3. If the Compute Engine API is on, lists the `default` network, its firewall rules, and any Editor grant to the Compute Engine default service account. It removes them only when run with `--apply-cleanup`.
4. Creates the two state buckets if they are missing, then reapplies every setting.
5. Prints the project labels and each bucket's settings and IAM policy.

It is safe to rerun.

### State buckets


| Bucket                                    | Holds state for     | Access                                                                       |
| ----------------------------------------- | ------------------- | ---------------------------------------------------------------------------- |
| `gke-build-proj-staging-identity-tfstate` | identity            | Project owners only                                                          |
| `gke-build-proj-staging-tfstate`          | foundation, staging | Project owners; the deployment service account is added by the identity root |


Both buckets are in `us-east4` with the Standard storage class, uniform bucket-level access, public access prevention, object versioning, and 7-day soft delete. An old state version is deleted once it is more than 30 days old and at least 10 newer versions exist. The automatic grants to project viewers and editors are removed, so project Viewer does not grant read access to state.

### Running it

List only, without deleting anything:

```bash
bash infra/init_bootstrap.sh
```

After reviewing the Compute Engine defaults it lists, remove them:

```bash
bash infra/init_bootstrap.sh --apply-cleanup
```

## Status


| Work             | Status  |
| ---------------- | ------- |
| Bootstrap script | Done    |
| Terraform roots  | Planned |


