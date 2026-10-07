# Pipeline

This is how I turn application source into a deployable image. Cloud Build tests, builds, and scans the API image on every pull request, and on every merge to `main` that changes the API it also publishes the image with its evidence. Run every command on this page from the repository root. The Terraform that creates the triggers, identities, and evidence bucket is in the [infrastructure README](../infra/README.md).

## Layout

| Path | Contents |
| --- | --- |
| [`cloudbuild-validate.yaml`](cloudbuild-validate.yaml) | Pull request build: test, build, and scan; nothing is pushed |
| [`cloudbuild-publish.yaml`](cloudbuild-publish.yaml) | Merge build: the same checks, then the scan report, SBOM, evidence upload, and push |
| [`install_tools.py`](install_tools.py) | Downloads Helm, kubeconform, the Kyverno CLI, Terraform, and Trivy for the validate build, each checked against a pinned SHA-256 |
| [`../apps/platform-verification-api/.trivyignore.yaml`](../apps/platform-verification-api/.trivyignore.yaml) | Vulnerabilities I have accepted for the API image, each with a reason and an expiry date |

## Triggers

Both triggers run in `us-east4` on the `staging-github` connection, which links this repository only.

| Trigger | Runs when | Runs as | Can |
| --- | --- | --- | --- |
| `staging-pr-validate` | A pull request targets `main`. A pull request from anyone but me waits until I comment `/gcbrun` | `staging-build-validate-sa` | Write build logs only |
| `staging-main-publish` | A merge to `main` changes `apps/platform-verification-api/**` or `pipeline/cloudbuild-publish.yaml`. Markdown files in the app folder are ignored, so a README change does not publish an image | `staging-build-publish-sa` | Write to the image repository; create and list objects in the evidence bucket, but not read, overwrite, or delete them |

`main` requires a pull request and a passing `staging-pr-validate` check, including for me. A change that only touches deployment configuration, such as `values-staging.yaml`, gets the validation check but never starts a publish build.

## What a build does

| Step | Validate | Publish | What it does |
| --- | --- | --- | --- |
| `test` | Yes | Yes | Installs `requirements-test.txt` in the image's own Python and runs `pytest` and `pip check` |
| `build` | Yes | Yes | Builds the image for `linux/amd64` and tags it `sha-<short commit>` |
| `export` | Yes | Yes | Saves the image to a tar in the workspace, so it can be scanned before it is pushed |
| `scan` | Yes | Yes | Trivy gate: fails on fixable MEDIUM, HIGH, or CRITICAL vulnerabilities and on any secret, after the accepted findings |
| `report` | No | Yes | Writes every finding, including accepted ones, to `scan.json` |
| `sbom` | No | Yes | Writes the image's package list to `sbom.cdx.json` (CycloneDX) |
| `evidence` | No | Yes | Copies both files to `gs://gke-build-proj-staging-build-evidence/platform-verification-api/<full commit>/` |
| Push | No | Yes | Pushes the image to `gke-build-proj-staging-images`, and Cloud Build records provenance for it |
| `tools` | Yes | No | Runs `install_tools.py` into `/workspace/bin` |
| `chart` | Yes | No | Runs `platform/tests/validate-chart.sh` with `SKIP_APP_TESTS=1`: chart renders against the Kubernetes schemas, invalid-input fixtures, and the admission policy fixtures |
| `terraform` | Yes | No | Runs `infra/tests/validate-terraform.sh`: format, no tfvars, init without a backend, validate with the lab on and off, and Trivy |

Every step must pass for the next one to run. In the validate build, `tools`, `chart`, and `terraform` run alongside the image steps. The push comes last, so an image is never published without its evidence: if the upload fails, nothing is pushed. Tags are immutable, so a published tag always names the same image.

Builder images are pinned by digest: Python 3.14.8 (the same image the Dockerfile uses), the Cloud Builders Docker image, Trivy 0.74.0, and the Cloud SDK 587.0.0 slim image. The validate build's tools are pinned by checksum in `install_tools.py`.

## Finding a published image

Set the commit you want:

```sh
FULL=$(git rev-parse HEAD)
IMG=us-east4-docker.pkg.dev/gke-build-proj/gke-build-proj-staging-images/platform-verification-api
```

The digest behind its tag:

```sh
gcloud artifacts docker images describe ${IMG}:sha-${FULL:0:7} --format="value(image_summary.digest)"
```

Its evidence, which must list `scan.json` and `sbom.cdx.json`:

```sh
gcloud storage ls gs://gke-build-proj-staging-build-evidence/platform-verification-api/$FULL/
```

Its provenance, which names the commit and the `staging-main-publish` trigger:

```sh
gcloud artifacts docker images describe ${IMG}:sha-${FULL:0:7} --show-provenance --format=json | grep -E "$FULL|staging-main-publish" | sort -u
```

Recent publish builds, with their commits and digests:

```sh
gcloud builds list --region=us-east4 --filter="substitutions.TRIGGER_NAME=staging-main-publish" --limit=5 --format="table(id,status,substitutions.COMMIT_SHA,results.images[0].digest)"
```

## Promoting an image to staging

Publishing does not deploy anything. A pull request chooses what staging runs:

1. Pick a publish build with status `SUCCESS` whose evidence exists.
2. Read its `scan.json` and decide whether you are happy with what it found.
3. In [`values-staging.yaml`](../platform/services/platform-verification-api/values-staging.yaml), set `image.repository` to the repository path, `image.digest` to the digest, and `releaseVersion` to `sha-<short commit>`.
4. Run `platform/tests/validate-chart.sh`, open a pull request, and merge it once the check passes.

Never promote `sha-b73554a`. It was built before the `evidence` step existed: it was pushed, then its evidence upload failed, so it has no scan report or SBOM.

## Accepting a vulnerability

When the scan blocks a build, fix it if you can: a newer base image or a dependency bump. If no fix is available yet, add an entry to [`.trivyignore.yaml`](../apps/platform-verification-api/.trivyignore.yaml) under `vulnerabilities`, with:

- the vulnerability ID as Trivy prints it
- a statement giving the reason, such as why the code path is not reachable
- an expiry date, about three months away at most, after which the build fails again

Accepted findings still appear in `scan.json`, marked as suppressed.

## Updating the base image

The base image digest appears in three places, and they must always match: the Dockerfile `FROM` line and the `test` step in both build files.

To check whether a fixed image exists:

1. Compare the digest pinned in the Dockerfile with the tag's current digest:

   ```sh
   docker buildx imagetools inspect python:3.14.8-slim-bookworm | sed -n 3p
   ```

2. If it differs, check the packages you need are fixed in the new image, for example:

   ```sh
   docker run --rm --platform linux/amd64 python:3.14.8-slim-bookworm@sha256:<new digest> dpkg-query -W libssl3 openssl
   ```

3. Update all three places, run the local gate below, and remove any accepted findings the new image fixes.

## Running the gate locally

Run the same build and scan before you push a change to the image:

```sh
docker build --platform linux/amd64 -t platform-verification-api:dryrun apps/platform-verification-api
docker save -o /tmp/pva-dryrun.tar platform-verification-api:dryrun
trivy image --input /tmp/pva-dryrun.tar --scanners vuln,secret --severity MEDIUM,HIGH,CRITICAL --ignore-unfixed \
  --ignorefile apps/platform-verification-api/.trivyignore.yaml --exit-code 1
```

A passing gate exits with code 0. Remove the tar and the `dryrun` image afterwards.

## Limits

- Image evidence is checked by hand before a promotion pull request, as described in [Promoting an image to staging](#promoting-an-image-to-staging); no pipeline step checks it.
- Images are not signed.
- Artifact Registry's own vulnerability scanning is off; Trivy is the only scanner.
- Evidence objects are deleted after 90 days, so an image can outlive its evidence.
