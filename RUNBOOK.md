# Runbook

This manual takes you from an empty Google Cloud project to a running GKE application platform, then covers building, releasing, operating, and tearing it down. The [evidence reports](platform/evidence/README.md) record what these procedures produced in the reference environment. For what each component is and why it is built this way, see the [README](README.md) and [architecture.md](architecture.md).

Run every command from the repository root, in zsh or bash, after you set the variables in [Set your variables](#set-your-variables). Check each step's expected result before you continue.

## Before you start

### What you need

- A Google Cloud project linked to a billing account, and a project-owner account. Project owners also administer the lab cluster.
- Permission on the billing account to link the project, create its budget, and set up the billing export.
- A public copy of this repository on GitHub, with admin rights to install the Cloud Build app and protect `main`. Argo CD reads the repository without credentials.
- A domain whose DNS host lets you add NS and DS records for a subdomain.
- An email address for alerts.

### Tools

| Tool | Version tested | Install on macOS |
| --- | --- | --- |
| Google Cloud CLI, with `bq` | 587.0.0 | `brew install --cask google-cloud-sdk` |
| GKE authentication plugin | Installed with gcloud | `gcloud components install gke-gcloud-auth-plugin` |
| Terraform | 1.16.4 | `brew install hashicorp/tap/terraform` |
| kubectl | 1.37.0 | `brew install kubectl` |
| Helm | 4.2.1 | `brew install helm` |
| kubeconform | 0.8.0 | `brew install kubeconform` |
| Kyverno CLI | 1.19.1 | `brew install kyverno` |
| Trivy | 0.74.0 | `brew install trivy` |
| Python | 3.14 | `brew install python@3.14` |
| Docker Desktop | 29.8.0 | From docker.com |
| crane | | `brew install crane` |
| GitHub CLI | | `brew install gh` |
| oha, for load tests | 1.16.0 | `brew install oha` |

Homebrew installs the newest releases; compare them with the tested versions, and keep kubectl within one minor version of the cluster. `dig` and `curl` come with macOS.

### Personal values

**These values belong to the reference environment. Replace them in your copy and push the change to your `main` before you provision anything.**

| Reference value | What it is | Where it is set |
| --- | --- | --- |
| `gke-build-proj` | Project ID. It also prefixes the state buckets, image repository, evidence bucket, and kubectl context name | `infra/env/staging/variables.tf` and `backend.tf`; `platform/argocd/` (kustomization, namespace, `bootstrap.sh`); `platform/kyverno/kustomization.yaml`; `platform/cluster/` (namespace, approved-registry policy); `platform/namespaces/local.yaml`; the API's values files; `platform/tests/` (live checks, policy fixtures) |
| `us-east4`, `us-east4-b` | Region and zone | `infra/env/staging/variables.tf`, and the same image paths and script defaults |
| `josephdara.com`, `gke.josephdara.com` | Parent domain, and the subdomain delegated to Cloud DNS | `infra/env/staging/main.tf` |
| `api.staging.gke.josephdara.com` | API hostname, built as `api.<environment>.<subdomain>` | `platform/services/platform-verification-api/values-staging.yaml` |
| `Josephdara/gke-platform` | GitHub repository | `infra/env/staging/main.tf`, `infra/modules/alerts/main.tf`, `platform/argocd/root/`, and the projects and Applications in `platform/cluster/` |
| `jd` | Owner label | `infra/env/staging/variables.tf`; the namespaces in `platform/argocd/namespace.yaml`, `platform/cluster/namespace-staging.yaml`, and `platform/namespaces/local.yaml`; the API's `values.yaml`; the policy fixtures |
| `josephdara`, `https://josephdara.com` | Chart maintainer | `platform/charts/service/Chart.yaml` |
| `gke_build_proj_staging_billing` | Billing export dataset | Created by hand |
| Alert email address, DNS host (Cloudflare), budget currency | Settings you make by hand | Console and DNS host only |

Keep the environment name `staging`: the Terraform root, manifest paths, namespaces, and scripts use it. When you change the policy fixtures, keep each one's purpose: the compliant fixture passes, and every other fixture fails for its one reason.

List every configuration line that still holds a reference value:

```bash
git grep -nwE "gke-build-proj|[Jj]osephdara|us-east4|jd" -- ':!*.md'
```

The Markdown files keep the reference values as a record of the reference environment.

### Set your variables

Set these in every terminal you use. **Replace each `YOUR_` value with your own.**

```bash
# Personal values.
export PROJECT_ID=YOUR_PROJECT_ID
export DNS_ZONE_NAME=YOUR_DELEGATED_SUBDOMAIN
export PARENT_DOMAIN=YOUR_PARENT_DOMAIN
export OWNER=YOUR_OWNER_LABEL
export BILLING_DATASET=YOUR_BILLING_DATASET
# Region and zone: match your checked-in configuration.
export REGION=us-east4 ZONE=us-east4-b ENVIRONMENT=staging
# Derived names.
export API_HOST=api.$ENVIRONMENT.$DNS_ZONE_NAME URL=https://api.$ENVIRONMENT.$DNS_ZONE_NAME/
export CLUSTER=$ENVIRONMENT-super-cluster APP=$ENVIRONMENT-platform-verification-api
export CONTEXT=gke_${PROJECT_ID}_${ZONE}_$CLUSTER
export IMG=$REGION-docker.pkg.dev/$PROJECT_ID/$PROJECT_ID-$ENVIRONMENT-images/platform-verification-api
export MIRROR=$REGION-docker.pkg.dev/$PROJECT_ID/$ENVIRONMENT-mirror
export EVIDENCE=gs://$PROJECT_ID-$ENVIRONMENT-build-evidence/platform-verification-api
```

`bootstrap.sh` and `live-checks.sh` read `CONTEXT`, so they target your cluster.

Define these helpers in each terminal. `add_demo_secret` adds a version to the API's demo secret without printing its private value:

```bash
add_demo_secret() (
  set -o pipefail
  demo_payload=$(python3 - "$1" <<'PY'
import json, re, secrets, sys
label = sys.argv[1]
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}", label):
    raise SystemExit("Use a label of 1 to 63 letters, digits, dots, underscores, or hyphens, starting with a letter or digit")
print(json.dumps({"label": label, "value": secrets.token_urlsafe(32)}), end="")
PY
  ) || exit 1
  printf '%s' "$demo_payload" | gcloud secrets versions add "${APP}-demo" --project="$PROJECT_ID" --data-file=-
)
```

`pq` runs a PromQL query against Managed Service for Prometheus and prints each series with its value:

```bash
pq() { curl -s -G "https://monitoring.googleapis.com/v1/projects/$PROJECT_ID/location/global/prometheus/api/v1/query" -H "Authorization: Bearer $(gcloud auth print-access-token)" --data-urlencode "query=$1" | python3 -c 'import json,sys; d=json.load(sys.stdin); [print(r["metric"], r["value"][1]) for r in d.get("data",{}).get("result",[])] or print(d)'; }
```

## Set up once

Do these in order. **Steps marked By hand are not represented in code**: they live in the Google Cloud console, GitHub, your DNS host, or local files that Git ignores.

| Step | How | Where it lives |
| --- | --- | --- |
| [Create the project and sign in](#create-the-project-and-sign-in) | By hand | Console and local gcloud credentials |
| [Run the bootstrap script](#run-the-bootstrap-script) | Script, with a local settings file | `infra/bootstrap/`; `infra/bootstrap/infra.env`, ignored by Git |
| [Set up the budget and billing export](#set-up-the-budget-and-billing-export) | By hand | Billing console and BigQuery |
| [Create the alert email channel](#create-the-alert-email-channel) | By hand | Cloud Monitoring |
| [Connect Cloud Build to GitHub](#connect-cloud-build-to-github) | By hand | Cloud Build console and the Cloud Build GitHub app |
| [Create the persistent resources](#create-the-persistent-resources) | Terraform | `infra/`; saved plans in `infra/private/`, ignored by Git |
| [Add secret values](#add-secret-values) | By hand | Secret Manager |
| [Delegate DNS to Cloud DNS](#delegate-dns-to-cloud-dns) | By hand | Your DNS host |
| [Mirror the controller images](#mirror-the-controller-images) | By hand | Artifact Registry |
| [Protect the main branch](#protect-the-main-branch) | By hand | GitHub repository settings |
| [Publish and release the first image](#publish-and-release-the-first-image) | Pipeline and pull request | `apps/`, `platform/services/` |

### Create the project and sign in

**By hand.** Sign in:

```bash
gcloud auth login
```

If the project does not exist yet, create it and link it to your billing account:

```bash
gcloud projects create "$PROJECT_ID"
gcloud billing projects link "$PROJECT_ID" --billing-account=YOUR_BILLING_ACCOUNT_ID
```

Set up Application Default Credentials for Terraform, with your project as the quota project, and sign in to GitHub:

```bash
gcloud config set project "$PROJECT_ID"
gcloud auth application-default login
gcloud auth application-default set-quota-project "$PROJECT_ID"
gh auth login
```

Check:

```bash
gcloud auth list --filter=status:ACTIVE
gcloud billing projects describe "$PROJECT_ID"
gh auth status
```

Expect your account, `billingEnabled: true`, and your GitHub account.

### Run the bootstrap script

**By hand**, create the script's settings file, which Git ignores:

```bash
printf 'PROJECT_ID=%s\nENV=%s\nREGION=%s\nSERVICE=platform\nOWNER=%s\n' "$PROJECT_ID" "$ENVIRONMENT" "$REGION" "$OWNER" > infra/bootstrap/infra.env
```

Enable Compute Engine first, so the script finds the defaults Compute Engine creates and removes them before Terraform runs. Then run the script in list-only mode:

```bash
gcloud services enable compute.googleapis.com --project="$PROJECT_ID"
bash infra/bootstrap/init_bootstrap.sh
```

The script enables the APIs Terraform needs, creates or updates the two state buckets, and lists the Compute Engine defaults: the `default` network, its firewall rules, and the Editor role on the Compute Engine default service account. Remove them:

```bash
bash infra/bootstrap/init_bootstrap.sh --apply-cleanup
```

Expect versioned state buckets with uniform access, public access prevention, 7-day soft delete, and access for project owners only. Terraform's state goes in `<project>-staging-tfstate`. The script is safe to rerun.

### Set up the budget and billing export

**By hand**, in the console:

1. Under Billing, then Budgets & alerts, create a monthly budget for this project only, with no credits or discounts selected, so spend is counted before credits. The reference budget is 100 in the billing account's currency, with email alerts to billing admins and users at 30%, 50%, and 99% of actual spend.
2. In BigQuery, create a dataset named after `$BILLING_DATASET` in the `US` multi-region. A multi-region dataset receives data from the start of the previous month.
3. Under Billing, then Billing export, turn on **Detailed usage cost** export to that dataset.

Billing data reaches the export within about a day of the usage. At the start of each lab session, check that the budget still belongs to the billing account the project is linked to. The budget sends alerts; the 24-hour session limit and the teardown keep spending down.

### Create the alert email channel

**By hand.** In Cloud Monitoring, under Alerting, then Edit notification channels, add an Email channel with the display name `staging-alerts`, which is `<environment>-alerts`. Check:

```bash
gcloud beta monitoring channels list --project="$PROJECT_ID" --type=email --filter='displayName="staging-alerts"' --format='table(displayName,type)'
```

Expect one email channel named `staging-alerts`. Terraform finds it by that name when it creates the alert policies at the start of each lab session.

### Connect Cloud Build to GitHub

**By hand.** Terraform links the repository and creates the build triggers, and they need this connection first:

1. In the console, open Cloud Build, then Repositories (2nd gen), and create a host connection to GitHub in your region named `staging-github`, which is `<environment>-github`.
2. When GitHub asks, install the Cloud Build app on your repository only.

Check:

```bash
gcloud builds connections describe staging-github --region="$REGION" --project="$PROJECT_ID" --format='value(installationState.stage)'
```

Expect `COMPLETE`. Google stores the connection's token in Secret Manager.

### Create the persistent resources

```bash
mkdir -p infra/private
terraform -chdir=infra/env/staging init
terraform -chdir=infra/env/staging plan -var=lab_enabled=false -out=../../private/persistent.tfplan
terraform -chdir=infra/env/staging show ../../private/persistent.tfplan
```

Review the plan, then apply it:

```bash
terraform -chdir=infra/env/staging apply ../../private/persistent.tfplan
```

This creates the APIs, the image and mirror repositories, the service accounts, the evidence bucket and build triggers, the secrets, the DNS zone, and the certificate. The [infrastructure README](infra/README.md#what-terraform-manages) lists every resource. Persistent resources are protected against deletion.

Pass `-var=lab_enabled=…` on every plan. It defaults to `false`, and a plan with `false` removes the lab.

### Add secret values

**By hand.** Terraform creates the secrets empty. Give the API's demo secret a version: a JSON object with a `label` that the API returns on `/` and a random `value` that it keeps private.

```bash
add_demo_secret v1
gcloud secrets versions list $APP-demo --project="$PROJECT_ID" --format="table(name.basename(),state)"
```

Expect one enabled version.

### Delegate DNS to Cloud DNS

**By hand, at your DNS host.** Terraform created the zone for your subdomain in Cloud DNS, with DNSSEC on, and the certificate's authorization record inside it. The parent domain must point to the zone.

**1. Read the delegation records**: the zone's name servers, its DS record (key tag, algorithm, digest type, and digest), and the parent domain's CAA records:

```bash
gcloud dns managed-zones describe $ENVIRONMENT-dns --project="$PROJECT_ID" --format="value(nameServers)"
gcloud dns dns-keys describe $(gcloud dns dns-keys list --zone=$ENVIRONMENT-dns --project="$PROJECT_ID" --filter="type=keySigning" --format="value(id)") --zone=$ENVIRONMENT-dns --project="$PROJECT_ID" --format="value(ds_record())"
dig CAA "$PARENT_DOMAIN" +short
```

**2. At your DNS host**, in the parent domain's records (Cloudflare in the reference environment), add:

- one NS record per name server, named after the subdomain's first label (`gke` in the reference environment), with the name server as its content and no trailing dot
- one DS record with the same name, filled in from the DS record
- a CAA record that allows `pki.goog`, if the parent domain has CAA records without it

**3. Check the delegation, then the authorization record through a public resolver that validates DNSSEC, then the certificate:**

```bash
dig NS "$DNS_ZONE_NAME" +short
dig @8.8.8.8 CNAME "_acme-challenge.${API_HOST}" +short
gcloud certificate-manager certificates describe $ENVIRONMENT-api-cert --project="$PROJECT_ID" --format="yaml(managed.state,managed.authorizationAttemptInfo)"
```

Expect the Cloud DNS name servers, a CNAME ending in `authorize.certificatemanager.goog.`, and, usually within an hour of the delegation resolving, `state: ACTIVE`.

### Mirror the controller images

**By hand.** Argo CD, Redis, and Kyverno run from your `staging-mirror` repository, at the digests pinned in `platform/argocd/kustomization.yaml` and `platform/kyverno/kustomization.yaml`. Copy each image unchanged, so its digest stays the same:

```bash
gcloud auth configure-docker $REGION-docker.pkg.dev
```

```bash
(
  set -e
  while IFS='|' read -r src dst; do
    crane copy "$src" "$MIRROR/$dst"
    digest=$(crane digest "$MIRROR/$dst")
    [ "${src##*@}" = "$digest" ]
    echo "$digest  $MIRROR/$dst"
  done <<'IMAGES'
reg.kyverno.io/kyverno/kyverno@sha256:b31d8511ae5fd6010e2a01ea72ebae08eb82fa51d91af14a1d9fe989949b4edb|kyverno/kyverno:v1.19.1
reg.kyverno.io/kyverno/kyvernopre@sha256:c25c47461f06f2845a48c319ae86fbbc1730a7b9ed5b701889c9dc1f9ee94b09|kyverno/kyvernopre:v1.19.1
reg.kyverno.io/kyverno/background-controller@sha256:8f1e9143373a27578cafc2d28d2c66ba0926c63b4c77e63de8d2fdd4a122859f|kyverno/background-controller:v1.19.1
reg.kyverno.io/kyverno/cleanup-controller@sha256:67a48e62a8d8f8120c86914ff822b90017c54054c7b64ef8a1555645e9d9761e|kyverno/cleanup-controller:v1.19.1
reg.kyverno.io/kyverno/reports-controller@sha256:c0eee97b9b44a0dd35805d56b358fa52548480f79d4944602b9609538eccd64c|kyverno/reports-controller:v1.19.1
quay.io/argoproj/argocd@sha256:dd3f47d5a5e4da563a7a398506e892481b358a7cec50abdf320c71aa55904bfa|argoproj/argocd:v3.5.3
public.ecr.aws/docker/library/redis@sha256:08ad0b1d280850169a790dba1393ff7a90aef951fc19632cf4d3ce4f78e679ba|library/redis:8.2.3-alpine
IMAGES
)
```

Expect 7 lines, each with the copy's digest. The block stops at the first failed copy or mismatched digest. If a registry answers `TOOMANYREQUESTS`, wait a minute and run it again. When you upgrade a controller, update this list with the digests in the kustomization files.

### Protect the main branch

**By hand, in GitHub.** Open a first pull request so the `staging-pr-validate` check runs once; GitHub offers only checks it has seen. Then add a branch protection rule for `main` under Settings, then Branches:

- Require a pull request before merging.
- Require status checks to pass before merging, with `staging-pr-validate (<your project ID>)` required, and require branches to be up to date before merging.
- Do not allow bypassing the above settings, so the rule applies to administrators too.

Expect the next pull request to show the check as required. Pull requests from people outside the repository wait until you comment `/gcbrun`.

### Publish and release the first image

Publish an image, as in [Publish an image](#publish-an-image), and release it, as in [Release an image](#release-an-image), before your first lab session; until then, `values-staging.yaml` names an image in the reference project. Argo CD deploys what is on your repository's `main` on GitHub, so push every personalized file there before the first bootstrap.

## Run a lab session

The network, router and NAT, cluster, the Gateway's static IP and DNS record, and the alert policies exist only during a lab session. Keep each session under 24 hours, including the teardown. In the reference environment, a day with the lab running cost $5.80 before credits.

### Start a session

Before you start, the one-time setup is complete, the certificate is `ACTIVE`, the controller images are mirrored, and `values-staging.yaml` names an image from your registry.

**1. Check the budget** still belongs to the project's billing account.

**2. Create the lab.** Expect 11 resources to add, including 3 alert policies:

```bash
terraform -chdir=infra/env/staging plan -var=lab_enabled=true -out=../../private/lab-on.tfplan
terraform -chdir=infra/env/staging show ../../private/lab-on.tfplan
```

Review the plan, then apply it. The apply takes about 10 minutes:

```bash
terraform -chdir=infra/env/staging apply ../../private/lab-on.tfplan
```

**3. Connect and bootstrap.** From an up-to-date `main`, get credentials through the cluster's DNS endpoint, then install Argo CD and hand the cluster to Git:

```bash
gcloud container clusters get-credentials "$CLUSTER" --zone="$ZONE" --project="$PROJECT_ID" --dns-endpoint
platform/argocd/bootstrap.sh
```

The bootstrap takes about 10 minutes and ends with `PASS  running image matches Git`. The load balancer needs a few more minutes before HTTPS answers.

### Check the platform

```bash
platform/tests/live-checks.sh
```

It runs 9 checks: Argo CD health, the running image against Git, the mounted secret, DNS and egress, network isolation, admission in and outside `staging`, developer access, and HTTPS. Exit code `0` means every check passed. If only HTTPS fails in the first few minutes after the bootstrap, wait about 5 minutes and run it again.

### End a session

**1. Stop reconciliation**, on the root Application first and then on the service, so Argo CD stops recreating resources:

```bash
kubectl --context "$CONTEXT" -n argocd patch applications.argoproj.io $ENVIRONMENT-platform --type merge -p '{"spec":{"syncPolicy":{"automated":null}}}'
kubectl --context "$CONTEXT" -n argocd patch applications.argoproj.io $APP --type merge -p '{"spec":{"syncPolicy":{"automated":null}}}'
```

**2. Delete the HTTPRoute and Gateway, and wait for GKE to remove the load balancer.** The loop waits until the project has no forwarding rules, target HTTPS proxies, URL maps, backend services, or health checks, so use it in a project that hosts only this platform:

```bash
kubectl --context "$CONTEXT" -n $ENVIRONMENT delete httproute,gateway --all
until [ -z "$(for r in forwarding-rules target-https-proxies url-maps backend-services health-checks; do gcloud compute $r list --project="$PROJECT_ID" --format='value(name)'; done)" ]; do sleep 20; done; date -u
```

**3. Remove the lab.** Expect 11 resources to destroy, all of them lab resources:

```bash
terraform -chdir=infra/env/staging plan -var=lab_enabled=false -out=../../private/lab-off.tfplan
terraform -chdir=infra/env/staging show ../../private/lab-off.tfplan
```

Review the plan, then apply it. The apply takes about 12 minutes:

```bash
terraform -chdir=infra/env/staging apply ../../private/lab-off.tfplan
```

**4. Check that nothing billable is left:**

```bash
gcloud container clusters list --project="$PROJECT_ID" --format="value(name)"; for r in instances disks addresses forwarding-rules target-https-proxies url-maps backend-services health-checks network-endpoint-groups routers networks firewall-rules; do echo "== $r"; gcloud compute $r list --project="$PROJECT_ID" --format="value(name)"; done
terraform -chdir=infra/env/staging plan -var=lab_enabled=false -detailed-exitcode; echo "exit=$?"
```

Expect empty lists, except that `networks` and `firewall-rules` may show resources from outside this platform, and `No changes` with `exit=0`. The state buckets, images, evidence, secrets, DNS zone, certificate, and billing data persist, with small storage and service charges.

## Change the platform

### Validate locally

Create the API's virtual environment once:

```bash
python3 -m venv apps/platform-verification-api/.venv
apps/platform-verification-api/.venv/bin/python -m pip install -r apps/platform-verification-api/requirements-test.txt
```

Before each pull request:

```bash
platform/tests/validate-chart.sh
infra/tests/validate-terraform.sh
```

Expect both to exit `0`. The first runs the API tests, renders the chart against the Kubernetes schemas, checks the invalid-input fixtures, and runs the admission policy tests. The second checks formatting, validates the configuration with the lab on and off, and runs a Trivy scan. When you change the image, also [scan it locally](#scan-an-image-locally).

### Open a pull request

Create the branch before you commit, so your `main` matches GitHub's after the squash merge:

```bash
git switch main && git pull --ff-only
git switch -c my-change
git status --short
```

Stage only the files you changed, then commit and open the pull request:

```bash
git add path/to/changed-file
git commit -m "describe the change"
git push -u origin my-change
gh pr create --base main --fill
gh pr checks --watch
```

After review and a passing check, merge and update your `main`:

```bash
gh pr merge --squash --delete-branch
git switch main && git pull --ff-only
```

The `staging-pr-validate` check runs the API tests, builds and scans the image, and runs the chart, policy, and Terraform checks.

### Release an image

1. Create a branch, as in [Open a pull request](#open-a-pull-request).
2. In `platform/services/platform-verification-api/values-staging.yaml`, set `image.repository` to your image repository, `image.digest` to the image's digest, and `releaseVersion` to `"sha-<short commit>"`. Keep each release in its own pull request.
3. Run `platform/tests/validate-chart.sh`, then open and merge the pull request.

Argo CD checks Git every 3 minutes and rolls out the new image without dropping below the ready replica count. The target is healthy within 10 minutes of the merge; in the reference environment, a release took 1 minute 37 seconds. During a lab session, run the live checks afterwards: they confirm the running image matches Git.

### Roll back a release

Release the last good digest again. Find its commit in the values file's history:

```bash
git switch main && git pull --ff-only && git switch -c rollback-release
git log --oneline -- platform/services/platform-verification-api/values-staging.yaml
```

Show the values file at that commit:

```bash
git show YOUR_KNOWN_GOOD_COMMIT:platform/services/platform-verification-api/values-staging.yaml
```

Copy only its `image.digest` and `releaseVersion` into the current file, and keep every other setting. Check that the image is still in the registry, using the digest with its `sha256:` prefix, then review and validate the change:

```bash
gcloud artifacts docker images describe "${IMG}@YOUR_KNOWN_GOOD_DIGEST" --format="value(image_summary.digest)"
git diff -- platform/services/platform-verification-api/values-staging.yaml
platform/tests/validate-chart.sh
```

Commit, push, and merge it as in [Open a pull request](#open-a-pull-request). No build runs, because the image is already in the registry. The target is healthy within 10 minutes of the merge; in the reference environment, a rollback took 1 minute 57 seconds.

### Change infrastructure

Plan with `lab_enabled` matching the lab's state: `true` during a session, `false` when the lab is off. Review the saved plan, then apply it:

```bash
terraform -chdir=infra/env/staging plan -var=lab_enabled=true -out=../../private/change.tfplan
terraform -chdir=infra/env/staging show ../../private/change.tfplan
```

```bash
terraform -chdir=infra/env/staging apply ../../private/change.tfplan
```

Changes to persistent resources take effect when you apply. Changes to lab resources, such as cluster settings or alert policies, take effect when you apply during a session, or when the next session creates the lab. After an apply during a session, run the live checks.

### Deploy on Docker Desktop

The [platform README](platform/README.md#local-deployment-on-docker-desktop) deploys the chart on Docker Desktop Kubernetes with a local registry, for trying chart changes without GCP.

## Build and scan images

Cloud Build runs the pipeline defined in `pipeline/`. The [pipeline README](pipeline/README.md) explains the design of each step.

### What the pipeline runs

| Trigger | Runs when | Runs as |
| --- | --- | --- |
| `staging-pr-validate` | A pull request targets `main`. Pull requests from people outside the repository wait until you comment `/gcbrun` | `staging-build-validate-sa`, which can write build logs only |
| `staging-main-publish` | A merge to `main` changes `apps/platform-verification-api/`, other than its Markdown files, or `pipeline/cloudbuild-publish.yaml` | `staging-build-publish-sa`, which can push to the image repository and create objects in the evidence bucket |

| Step | Validate | Publish | What it does |
| --- | --- | --- | --- |
| `test` | Yes | Yes | Installs `requirements-test.txt` in the image's Python and runs `pytest` and `pip check` |
| `build` | Yes | Yes | Builds the image for `linux/amd64`, tagged `sha-<short commit>` |
| `export` | Yes | Yes | Saves the image to a tar, so it is scanned before anything is pushed |
| `scan` | Yes | Yes | Trivy fails the build on fixable MEDIUM, HIGH, or CRITICAL vulnerabilities and on any secret, after the accepted findings in `.trivyignore.yaml` |
| `report` | No | Yes | Writes every finding, accepted ones included, to `scan.json` |
| `sbom` | No | Yes | Writes the image's package list to `sbom.cdx.json` in CycloneDX format |
| `evidence` | No | Yes | Copies both files to the evidence bucket, in a folder named after the full commit |
| Push | No | Yes | Pushes the image; Cloud Build records its provenance |
| `tools` | Yes | No | Installs Helm, kubeconform, the Kyverno CLI, Terraform, and Trivy, each checked against a pinned SHA-256 |
| `chart` | Yes | No | Runs `platform/tests/validate-chart.sh` without the app tests |
| `terraform` | Yes | No | Runs `infra/tests/validate-terraform.sh` |

Each step runs only after the one before it passes; in the validate build, `tools`, `chart`, and `terraform` run alongside the image steps. The push comes last, so a published image always has its evidence, and tags are immutable, so a tag always names the same image.

### Follow a build

Take the newest validate build, or set `BUILD` to an ID from `gh pr checks`:

```bash
BUILD=$(gcloud builds list --region=$REGION --project="$PROJECT_ID" --filter="substitutions.TRIGGER_NAME=$ENVIRONMENT-pr-validate" --limit=1 --format="value(id)"); echo $BUILD
```

Each step's status, then the build's log:

```bash
gcloud builds describe $BUILD --region=$REGION --project="$PROJECT_ID" --format="table[box](steps.id,steps.status)"
gcloud builds log $BUILD --region=$REGION --project="$PROJECT_ID"
```

Read the failing step's log before you change anything. To run the validate check again, push a new commit to the pull request's branch.

### Scan an image locally

These run the pipeline's `build`, `export`, `scan`, `report`, and `sbom` steps on your machine, with the same Trivy flags. Docker Desktop must be running.

```bash
docker build --platform linux/amd64 -t platform-verification-api:dryrun apps/platform-verification-api
docker save -o /tmp/pva-dryrun.tar platform-verification-api:dryrun
```

The gate. Exit code `0` means the pipeline's `scan` step would pass:

```bash
trivy image --input /tmp/pva-dryrun.tar --scanners vuln,secret --severity MEDIUM,HIGH,CRITICAL --ignore-unfixed --ignorefile apps/platform-verification-api/.trivyignore.yaml --exit-code 1
```

The full report, with accepted findings marked as suppressed, the SBOM, and the report as a table:

```bash
trivy image --input /tmp/pva-dryrun.tar --scanners vuln,secret --ignorefile apps/platform-verification-api/.trivyignore.yaml --show-suppressed --format json --output /tmp/scan.json
trivy image --input /tmp/pva-dryrun.tar --format cyclonedx --output /tmp/sbom.cdx.json
trivy convert --format table /tmp/scan.json
```

Scan the Terraform on its own, as `validate-terraform.sh` does:

```bash
trivy config --quiet --misconfig-scanners terraform --severity HIGH,CRITICAL,MEDIUM --exit-code 1 --ignorefile infra/.trivyignore.yaml --skip-dirs infra/private --skip-dirs '**/.terraform' --tf-vars infra/tests/lab-on.tfvars infra
```

Clean up:

```bash
rm -f /tmp/pva-dryrun.tar /tmp/scan.json /tmp/sbom.cdx.json && docker image rm platform-verification-api:dryrun
```

### Publish an image

A merge that changes `apps/platform-verification-api/`, other than its Markdown files, starts the publish build. After the merge, wait for `SUCCESS` on your commit:

```bash
git switch main && git pull --ff-only && FULL=$(git rev-parse HEAD)
gcloud builds list --region=$REGION --project="$PROJECT_ID" --filter="substitutions.TRIGGER_NAME=$ENVIRONMENT-main-publish" --limit=2 --format="table(id,status,substitutions.COMMIT_SHA,results.images[0].digest)"
```

If newer commits have reached `main` since, set `FULL` to the commit the publish build ran for. Then read the image's digest, its evidence, and its provenance:

```bash
gcloud artifacts docker images describe "${IMG}:sha-${FULL:0:7}" --format="value(image_summary.digest)"
gcloud storage ls $EVIDENCE/$FULL/
gcloud artifacts docker images describe "${IMG}:sha-${FULL:0:7}" --show-provenance --format=json | grep -E "$FULL|$ENVIRONMENT-main-publish" | sort -u
```

Expect the build's digest, both `scan.json` and `sbom.cdx.json`, and provenance naming the commit and the trigger. Read the scan report before you release the image. It lists every finding, including the accepted ones:

```bash
gcloud storage cp $EVIDENCE/$FULL/scan.json /tmp/scan.json && trivy convert --format table /tmp/scan.json
```

### When a scan blocks a build

Read the failing step's log, as in [Follow a build](#follow-a-build), or run the gate locally to see the findings. Fix the finding if you can.

For a finding in the base image, check whether a newer image exists. Print the tag's current digest and compare it with the one in the Dockerfile's `FROM` line:

```bash
docker buildx imagetools inspect python:3.14.8-slim-bookworm | sed -n 3p
```

Check that the new image has the fixed package versions, for example:

```bash
docker run --rm --platform linux/amd64 python:3.14.8-slim-bookworm@sha256:NEW_DIGEST dpkg-query -W libssl3 openssl
```

Replace the digest everywhere it is pinned, in the Dockerfile and in the build files' steps, then run the local gate. This lists the pins, including the Markdown files that mention the image:

```bash
git grep -n "python:3.14.8-slim-bookworm@sha256"
```

For a finding in a Python package, raise its pin in `apps/platform-verification-api/requirements.txt`.

If no fix exists yet, accept the finding with a reason and an expiry date, at most about three months away. Image findings go in `apps/platform-verification-api/.trivyignore.yaml`, under `vulnerabilities`:

```yaml
  - id: CVE-2026-13221
    statement: "Why the finding does not affect the service, and when to remove the entry."
    expired_at: 2026-10-19
```

Terraform findings go in `infra/.trivyignore.yaml`, under `misconfigurations`, with paths relative to `infra/`:

```yaml
  - id: GCP-0076
    paths:
      - "modules/network/main.tf"
    statement: "Why the finding is acceptable here."
    expired_at: 2027-01-01
```

After its expiry date, an entry stops applying and the finding fails the build again. List every accepted finding with its expiry date:

```bash
awk '/- id:/{id=$3} /expired_at/{print FILENAME, id, $2}' apps/platform-verification-api/.trivyignore.yaml infra/.trivyignore.yaml
```

## Operate the platform

These procedures run during a lab session, after the bootstrap.

### Check status

```bash
kubectl --context "$CONTEXT" -n argocd get applications.argoproj.io -o custom-columns=NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status,REVISION:.status.sync.revision
kubectl --context "$CONTEXT" -n $ENVIRONMENT get deployment,pods,hpa,pdb
```

Expect every Application `Synced` and `Healthy`, ready API Pods, and the HPA between 2 and 3 replicas. If an Application is not Synced, its conditions say why:

```bash
kubectl --context "$CONTEXT" -n argocd get applications.argoproj.io $APP -o jsonpath='{range .status.conditions[*]}{.type}: {.message}{"\n"}{end}'
```

### Rotate a secret

Record the current version, then add one with a new label:

```bash
OLD_VERSION=$(gcloud secrets versions describe latest --secret=$APP-demo --project="$PROJECT_ID" --format="value(name.basename())"); echo "Replacing version $OLD_VERSION"
NEW_LABEL=rotation-$(date -u +%Y%m%dT%H%M%SZ)
add_demo_secret $NEW_LABEL
```

The Secret Manager add-on refreshes each Pod's mounted file every 2 minutes, and the API reloads it on its next request, without a restart. After about 2 minutes, print the label every API Pod serves:

```bash
for pod in $(kubectl --context "$CONTEXT" -n $ENVIRONMENT get pods -l app.kubernetes.io/instance=$APP -o name); do kubectl --context "$CONTEXT" -n $ENVIRONMENT exec $pod -- python -c 'import json,urllib.request; print(json.load(urllib.request.urlopen("http://127.0.0.1:8080/", timeout=5))["secretLabel"])'; done
```

When every Pod prints the new label, disable the old version:

```bash
gcloud secrets versions disable $OLD_VERSION --secret=$APP-demo --project="$PROJECT_ID"
```

In the reference environment, a new version reached every Pod within 60 seconds. A version with an invalid label or an empty value is logged as `secret_reload_failed`, and the Pods keep serving the last valid one.

### Investigate an alert

Terraform creates these alerts with the lab. They email the `staging-alerts` channel:

| Alert | Severity | Fires when |
| --- | --- | --- |
| `staging-no-ready-replicas` | Critical | A `staging-*` Deployment has had no available replicas for 2 minutes |
| `staging-error-rate` | Warning | More than 1% of a service's requests returned a 5xx status for 5 minutes, while it handled at least 1 request per second |
| `staging-latency` | Warning | A service's p95 latency stayed above 500 ms for 5 minutes |

The email names the policy, the Deployment or service, the value that crossed the threshold, and the alert's description. In the reference environment, the zero-replicas email arrived 3 to 4 minutes after the last replica went, and a recovery email 5 to 6 minutes after the Pods were ready again.

The error-rate and latency alerts read the API's own metrics. Check from outside too, because the load balancer answers some failures itself, such as a 503 while no Pod is ready:

```bash
curl -s -o /dev/null -w "HTTPS %{http_code}\n" $URL
```

**1. Run the live checks.** A failing check names the layer:

```bash
platform/tests/live-checks.sh
```

**2. Look at the Pods and recent events.** Probe failures, mount failures, and `LoadBalancerNegNotReady`, meaning the load balancer has not yet marked a new Pod healthy, show up here:

```bash
kubectl --context "$CONTEXT" -n $ENVIRONMENT get pods -l app.kubernetes.io/instance=$APP -o wide
kubectl --context "$CONTEXT" -n $ENVIRONMENT get events --sort-by=.lastTimestamp | tail -n 15
```

**3. Read the metrics.** Every series carries `version`, the release's `releaseVersion`, which is `sha-` and the commit the image was built from, so a problem that starts with a new `version` points at that release:

```bash
pq 'up{namespace="staging"}'
pq 'sum by (version, route, status) (increase(http_requests_total{namespace="staging"}[10m]))'
pq 'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{namespace="staging"}[10m])))'
```

The last query is the API's own p95 in seconds. Under load it stayed at or below 5 ms while clients over the internet saw 40 to 60 ms, so a high client latency with a low API latency points at the network or the load balancer.

**4. Recover.** If the problem started with a release, [roll it back](#roll-back-a-release). A Deployment scaled to 0 by hand stays at 0, because Git sets no replica count and the autoscaler pauses at 0; scale it back:

```bash
kubectl --context "$CONTEXT" -n $ENVIRONMENT scale deployment $APP --replicas=2
kubectl --context "$CONTEXT" -n $ENVIRONMENT rollout status deployment $APP --timeout=3m
```

### Drain a node

**1. Check the versions, the disruption budget, which must allow 1 disruption, and the live checks:**

```bash
gcloud container clusters describe "$CLUSTER" --zone="$ZONE" --project="$PROJECT_ID" --format="value(currentMasterVersion,currentNodeVersion)"
kubectl --context "$CONTEXT" -n $ENVIRONMENT get pdb,hpa
platform/tests/live-checks.sh
```

**2. Drain the node running the first API Pod**, or set `NODE` to any node:

```bash
NODE=$(kubectl --context "$CONTEXT" -n $ENVIRONMENT get pods -l app.kubernetes.io/instance=$APP -o jsonpath='{.items[0].spec.nodeName}'); echo $NODE
kubectl --context "$CONTEXT" drain $NODE --ignore-daemonsets --delete-emptydir-data --timeout=8m
```

Under 20 requests per second in the reference environment, the drain took 35 seconds. The evicted API Pod's replacement served through the load balancer about 30 seconds after it was scheduled, while the other API Pod kept serving. The cluster autoscaler added a third node within about 70 seconds, and 53 of 12,000 requests got a 503. Admission in `staging` fails closed, so if the Kyverno admission controller is on the drained node, new Pods in `staging` start once it is running again elsewhere.

**3. Return the node to service**, also when the drain times out, then run the live checks:

```bash
kubectl --context "$CONTEXT" uncordon $NODE
platform/tests/live-checks.sh
```

About 10 minutes later, the autoscaler may remove the emptiest node.

### Run the acceptance tests

These repeat the load and failure tests in the [acceptance report](platform/evidence/2026-10-07-acceptance.md), against the targets in [architecture.md](architecture.md). Run each test on its own, with 2 ready replicas and passing live checks before it starts. In a second terminal, log the autoscaler, the API's Pods, and the nodes every 5 seconds:

```bash
while true; do echo "$(date -u +%T) hpa=$(kubectl --context $CONTEXT -n $ENVIRONMENT get hpa $APP -o jsonpath='{.status.currentMetrics[0].resource.current.averageUtilization}%/{.status.currentReplicas}->{.status.desiredReplicas}') pods=$(kubectl --context $CONTEXT -n $ENVIRONMENT get pods -l app.kubernetes.io/instance=$APP -o wide --no-headers | awk '{printf "%s:%s:%s@%s ", substr($1,length($1)-4), $2, $3, substr($7,length($7)-3)}') nodes=$(kubectl --context $CONTEXT get nodes --no-headers | awk '{printf "%s:%s ", substr($1,length($1)-3), $2}')"; sleep 5; done | tee -a watch.log
```

| Test | Command | Passes when | Reference result |
| --- | --- | --- | --- |
| Steady load | `oha -z 10m -q 20 --no-tui $URL` | Under 1% errors and p95 below 500 ms | 99.78% HTTP 200, p95 56 ms |
| Autoscaling | `oha -z 6m -q 150 --no-tui $URL` | The HPA scales within 3 minutes of CPU passing its 70% target | 2 to 3 replicas; 99.88% HTTP 200, p95 42 ms |
| Pod failure | With the steady load running: `kubectl --context $CONTEXT -n $ENVIRONMENT delete pod $(kubectl --context $CONTEXT -n $ENVIRONMENT get pods -l app.kubernetes.io/instance=$APP -o jsonpath='{.items[0].metadata.name}') --grace-period=0 --force` | The replacement is ready within 2 minutes; under 1% errors | Ready in 22 seconds; 99.22% HTTP 200 |
| Node drain | With the steady load running: [Drain a node](#drain-a-node) | No total outage; under 1% errors and p95 below 500 ms | 99.56% HTTP 200, p95 55 ms |
| Alert delivery | `kubectl --context $CONTEXT -n $ENVIRONMENT scale deployment $APP --replicas=0`, wait for the email, then scale back as in [Investigate an alert](#investigate-an-alert) | The email arrives within 5 minutes of the condition qualifying | 3 to 4 minutes after the last replica went |

To time a Pod replacement, read each Pod's creation and Ready times:

```bash
kubectl --context "$CONTEXT" -n $ENVIRONMENT get pods -l app.kubernetes.io/instance=$APP -o custom-columns='NAME:.metadata.name,CREATED:.metadata.creationTimestamp,READY:.status.conditions[?(@.type=="Ready")].lastTransitionTime,NODE:.spec.nodeName'
```

`oha` reports any HTTP response as a success, so count only its `[200]` responses against the total, and leave out requests still in flight when the run ends. The acceptance report keeps the node upgrade rehearsal open: the recorded attempt replaced no nodes.

### Check costs

Billing data reaches the export within about a day. Spend, credits, and net cost per day and Google Cloud service:

```bash
bq query --use_legacy_sql=false --project_id="$PROJECT_ID" "
SELECT DATE(usage_start_time) AS day, service.description AS service,
  ROUND(SUM(cost), 2) AS cost,
  ROUND(SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)), 2) AS credits,
  ROUND(SUM(cost + IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)), 2) AS net_cost
FROM \`${PROJECT_ID}.${BILLING_DATASET}.gcp_billing_export_resource_v1_*\`
WHERE project.id = '${PROJECT_ID}'
GROUP BY day, service HAVING cost > 0 ORDER BY day, cost DESC"
```

GKE cost allocation by namespace and `service` label. `kube:unallocated` is idle capacity, `kube:system-overhead` is reserved for the node's system, and `(none)` is cost no namespace owns, such as the cluster fee:

```bash
bq query --use_legacy_sql=false --project_id="$PROJECT_ID" "
SELECT DATE(usage_start_time) AS day,
  IFNULL((SELECT value FROM UNNEST(labels) WHERE key = 'k8s-namespace'), '(none)') AS namespace,
  IFNULL((SELECT value FROM UNNEST(labels) WHERE key = 'k8s-label/service'), '(none)') AS service_label,
  ROUND(SUM(cost), 2) AS cost
FROM \`${PROJECT_ID}.${BILLING_DATASET}.gcp_billing_export_resource_v1_*\`
WHERE (SELECT value FROM UNNEST(labels) WHERE key = 'goog-k8s-cluster-name') = '${CLUSTER}'
GROUP BY day, namespace, service_label HAVING cost > 0 ORDER BY day, cost DESC"
```

Spend by SKU and Terraform `component` label:

```bash
bq query --use_legacy_sql=false --project_id="$PROJECT_ID" "
SELECT service.description AS service, sku.description AS sku,
  IFNULL((SELECT value FROM UNNEST(labels) WHERE key = 'component'), '(none)') AS component,
  ROUND(SUM(cost), 2) AS cost
FROM \`${PROJECT_ID}.${BILLING_DATASET}.gcp_billing_export_resource_v1_*\`
WHERE project.id = '${PROJECT_ID}'
GROUP BY service, sku, component HAVING cost > 0.005 ORDER BY cost DESC LIMIT 40"
```

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| The bootstrap or live checks print `Cannot reach context` | No credentials for the cluster, or `CONTEXT` names another cluster | Get credentials as in [Start a session](#start-a-session), and check that `CONTEXT` is `gke_<project>_<zone>_<cluster>` |
| The bootstrap times out with the root Application `OutOfSync/Missing` and `failed to discover server resources for group version policies.kyverno.io/v1` | Argo CD validates every resource before the first wave, and the policy CRDs arrive with Kyverno in an earlier wave | The policies carry `argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true`. Give the same annotation to any resource whose CRD another Application installs |
| Both Applications show `Synced/Degraded` for a few seconds near the end of the bootstrap | Most likely the HPA's health before its first CPU metrics | Wait; they settle at `Synced/Healthy` |
| HTTPS returns 404, or only the HTTPS live check fails, right after the bootstrap | The global load balancer is still being programmed | Wait about 5 minutes, then rerun the live checks |
| The certificate stays `PROVISIONING`, or reports that the domain has no CNAME record | The delegation is not live yet, or the DS record does not match | Repeat the checks in [Delegate DNS to Cloud DNS](#delegate-dns-to-cloud-dns). If `dig @8.8.8.8 CNAME "_acme-challenge.${API_HOST}" +short +cd` answers while the same query without `+cd` does not, correct the DS record |
| The mirror block stops with `TOOMANYREQUESTS` | The upstream registry's rate limit | Run the block again after a minute |
| A plan with the lab on fails to find the notification channel | No channel has the display name `staging-alerts` | [Create the alert email channel](#create-the-alert-email-channel) |
| A Deployment in `staging` is denied by `vpol.validate.kyverno.svc-fail` | It breaks an admission policy | Each message names the field and the fix; the [platform README](platform/README.md#admission-policies) lists the policies |
| A new Pod stays `ContainerCreating` with `FailedMount` and `PermissionDenied` | Its Kubernetes service account has no grant on the secret | Add the secret to that service in `service_secrets` in `infra/env/staging/main.tf`, then plan and apply |
| GitHub refuses a merge although the checks passed | The required check must pass on the branch as updated with `main` | Wait for the new check run, then merge |
| `zsh: bad substitution` on a command with `$IMG:sha-…` | zsh reads `:s` after a variable as a modifier | Write `${IMG}:sha-…` |
| Load balancer resources remain after the Gateway is deleted | Backend services and health checks are removed last | Use the wait loop in [End a session](#end-a-session) before the lab-off apply |
| `git pull --ff-only` refuses after a squash merge | The commit was made on `main` before the branch was created | Run `git pull --rebase`; Git drops the local commit, whose changes the squash already contains |

## Reference

- [README](README.md): what the platform does, its results, and its limitations.
- [architecture.md](architecture.md): the design decisions and the acceptance targets.
- [Infrastructure README](infra/README.md): the Terraform modules and every GCP resource.
- [Platform README](platform/README.md): Argo CD, the chart, its inputs, the admission policies, and chart validation.
- [Pipeline README](pipeline/README.md): the build steps, vulnerability exceptions, and base image updates.
- [Applications README](apps/README.md): testing and running the API's image.
- [Evidence index](platform/evidence/README.md): every lab session report.
