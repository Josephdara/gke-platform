# Platform

This is the Kubernetes side of the platform: the shared Helm chart, each service's chart values, namespace manifests, and the chart validation script. Run every command on this page from the repository root. The project overview is in the [root README](../README.md), and the Python service and its image are in the [applications README](../apps/README.md).

## Layout


| Path                                                                         | Contents                                                                                                                    |
| ---------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `[charts/service/](charts/service/)`                                         | Shared Helm chart that deploys one HTTP service                                                                             |
| `[services/platform-verification-api/](services/platform-verification-api/)` | Chart values for the API: `values.yaml` (shared) plus one environment file, `values-staging.yaml` or `values-local.yaml`    |
| `[namespaces/](namespaces/)`                                                 | Local namespace manifest that enforces the Pod Security "restricted" profile                                                |
| `[tests/](tests/)`                                                           | Chart validation script; its fixtures live in `charts/service/tests/fixtures/`                                              |
| `[argocd/](argocd/)`                                                         | Argo CD install overlay, the root project and Application, and `bootstrap.sh`                                               |
| `[cluster/](cluster/)`                                                       | What the root Application manages: the `staging` namespace, the `staging-services` project, and one Application per service |
| `[evidence/](evidence/)`                                                     | Reports from lab sessions: what was run, versions, timings, expected and actual results                                     |


`values-staging.yaml` holds the digest of an image the pipeline published. Changing it chooses what staging runs; see [Promoting an image to staging](../pipeline/README.md#promoting-an-image-to-staging).

## GitOps with Argo CD

On the lab cluster, Argo CD deploys whatever `main` declares. I never apply application manifests myself: I change Git through a pull request, and Argo CD makes the cluster match within a few minutes.

### What runs and who owns what

I install Argo CD 3.5.3 as the **core** install: the application controller, repo server, Redis, and ApplicationSet controller, with no API server, web UI, or SSO. Nothing is exposed from the private cluster. It polls this repository every 180 seconds through Cloud NAT and renders the chart with its bundled Helm 4.2.1, the same version I use locally.


| Layer                                                                                             | Files                                                                   | Applied by                              |
| ------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | --------------------------------------- |
| Argo CD and its settings                                                                          | `argocd/kustomization.yaml`, `argocd/namespace.yaml`, `argocd/patches/` | `bootstrap.sh`                          |
| Root project `platform` and root Application `staging-platform`                                   | `argocd/root/`                                                          | `bootstrap.sh`                          |
| `staging` namespace (Pod Security "restricted"), `staging-services` project, service Applications | `cluster/`                                                              | The root Application, from `main`       |
| Each service's Deployment, Service, ConfigMap, and ServiceAccount                                 | `charts/service/` with `services/<service>/` values                     | That service's Application, from `main` |


The overlay pins the upstream `core-install.yaml` to tag `v3.5.3`, pins every Argo CD and Redis image by digest, adds resource requests, sets the 180-second polling interval, and adds a health check for Applications so the root waits until each service is healthy.

The two projects are guardrails. `platform` may only create Namespaces, AppProjects, and Applications. `staging-services` may only deploy to `staging`, may create no cluster-wide objects, and allows only ServiceAccount, ConfigMap, Service, and Deployment. Argo CD refuses anything else; add a kind here when the chart starts rendering it.

Service Applications sync automatically, revert manual changes in the cluster (self-heal), and delete what is removed from Git (prune). The root also syncs automatically and self-heals, but never prunes, so a mistaken commit cannot delete the `staging` namespace.

### Bootstrapping

Start a lab session as described in the [infrastructure README](../infra/README.md#start-a-session), then run this from an up-to-date `main`:

```sh
platform/argocd/bootstrap.sh
```

It checks it can reach the staging cluster, installs Argo CD with server-side apply, waits for the CRDs and controllers, applies the root, and waits until both Applications are Synced and Healthy. It then reads `values-staging.yaml` at the commit Argo CD synced and compares its digest with the image the pods are running. A successful run ends with:

```text
  Bundled Helm:     v4.2.1+...
PASS  running image matches Git
```

It is safe to rerun. In my last session it took about two and a half minutes.

### Checking status

```sh
kubectl --context gke_gke-build-proj_us-east4-b_staging-super-cluster -n argocd get applications.argoproj.io \
  -o custom-columns=NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status,REVISION:.status.sync.revision
```

If an Application is not Synced, its conditions say why:

```sh
kubectl --context gke_gke-build-proj_us-east4-b_staging-super-cluster -n argocd get applications.argoproj.io <name> \
  -o jsonpath='{range .status.conditions[*]}{.type}: {.message}{"\n"}{end}'
```

`InvalidSpecError` means a project does not allow what the Application asks for. `ComparisonError` usually means the chart failed to render; reproduce it with `helm template` as in [Testing the Helm chart](#testing-the-helm-chart). Synced but Degraded means Argo CD applied exactly what Git says and the release itself is broken: fix it or revert it in Git.

### Releasing and rolling back

To release, open a pull request that changes `image.digest` and `releaseVersion` in `values-staging.yaml`, as described in [Promoting an image to staging](../pipeline/README.md#promoting-an-image-to-staging), and merge it. To roll back, revert that commit through another pull request. Neither starts a build: the revert brings back the previous digest, which is still in the registry.

In my last session, both took under two minutes from merge to healthy. Most of that is Argo CD waiting for its next poll; the rollout itself took under 30 seconds, without ever dropping below two ready pods.

Do not use `kubectl rollout undo` or edit objects by hand: self-heal puts Git's version back within seconds.

### Stopping reconciliation

Before you remove the lab, turn off automated sync on the root Application first and then on each service Application, as in [End a session](../infra/README.md#end-a-session). The root manages the service Applications, so a change made to a service Application first is undone by the root.

### Changing Argo CD

- **Upgrading:** change the tag in the resource URL, `newTag`, and both digests in `argocd/kustomization.yaml`. If the new release bundles a different Helm version, check that it renders the chart identically before switching, and update your local Helm. Run `kubectl kustomize platform/argocd` and check the patches still apply.
- **Settings:** edit `argocd/patches/`. The bootstrap applies them, not Argo CD, so rerun the bootstrap after merging.
- **Adding a service:** add an Application file in `cluster/apps/`, pointing at the shared chart and the service's values. The root creates it after the merge.



## Local deployment on Docker Desktop

I ran every step in this section on Docker Desktop, and all checks passed.

### Prerequisites

You need Docker Desktop with Kubernetes enabled (kubeadm, single node). On Apple Silicon the node is `arm64`. Every `kubectl` command here names `--context docker-desktop`, so none of them can reach another cluster. Confirm the context and the node architecture:

```sh
kubectl config get-contexts
kubectl --context docker-desktop get nodes -L kubernetes.io/arch
```

Start a local registry on port 5001, bound to `127.0.0.1` only. I avoid port 5000 because macOS AirPlay Receiver uses it:

```sh
docker run -d --restart unless-stopped -p 127.0.0.1:5001:5000 --name local-registry registry:2
curl -s http://localhost:5001/v2/_catalog
```



### Build, scan, and publish

Commit your application changes first. The image tag uses the last commit that touched the application, so it names the exact source. This must print nothing:

```sh
git status --porcelain apps/platform-verification-api
```

Set the tag once for this shell:

```sh
TAG=local-$(git log -1 --format=%h -- apps/platform-verification-api)
```

Build for `arm64`:

```sh
docker build --platform linux/arm64 \
  -t localhost:5001/platform-verification-api:$TAG \
  apps/platform-verification-api
```

Scan before you publish. Fixable MEDIUM, HIGH, or CRITICAL vulnerabilities block publication, as they do in the pipeline, and the gate exits with code 1 when it finds any. The secret scan must report no findings, and the image user must be `10001:10001`:

```sh
trivy image --scanners vuln --severity MEDIUM,HIGH,CRITICAL --ignore-unfixed --exit-code 1 \
  --ignorefile apps/platform-verification-api/.trivyignore.yaml \
  localhost:5001/platform-verification-api:$TAG
trivy image --scanners secret localhost:5001/platform-verification-api:$TAG
docker image inspect --format '{{.Config.User}}' localhost:5001/platform-verification-api:$TAG
```

Push, then read the digest from the registry's `Docker-Content-Digest` header:

```sh
docker push localhost:5001/platform-verification-api:$TAG
curl -sI \
  -H 'Accept: application/vnd.oci.image.index.v1+json' \
  -H 'Accept: application/vnd.docker.distribution.manifest.list.v2+json' \
  -H 'Accept: application/vnd.oci.image.manifest.v1+json' \
  -H 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
  http://localhost:5001/v2/platform-verification-api/manifests/$TAG
```

After every rebuild, set `image.digest` in `values-local.yaml` to that digest and `releaseVersion` to the new tag. Docker's local image ID is not the registry digest, so don't use it.

### Deploy

Create the namespace and confirm its Pod Security labels:

```sh
kubectl --context docker-desktop apply -f platform/namespaces/local.yaml
kubectl --context docker-desktop get namespace local --show-labels
```

Render with both values files; the later file overrides the shared one. Then run a server-side dry run, which validates against the API schema and admission (including the "restricted" profile) without creating anything. Expect four `(server dry run)` lines and no warnings:

```sh
mkdir -p /tmp/pva-local
helm template platform-verification-api platform/charts/service \
  -f platform/services/platform-verification-api/values.yaml \
  -f platform/services/platform-verification-api/values-local.yaml \
  --namespace local > /tmp/pva-local/manifests.yaml
kubectl --context docker-desktop apply --dry-run=server -f /tmp/pva-local/manifests.yaml
```

Apply and wait for the rollout:

```sh
kubectl --context docker-desktop apply -f /tmp/pva-local/manifests.yaml
kubectl --context docker-desktop -n local rollout status \
  deployment/local-platform-verification-api --timeout=120s
```



### Checks

**A. Healthy start.** Expect two pods at `1/1`, no restarts, and no warning events:

```sh
kubectl --context docker-desktop -n local get pods -o wide
kubectl --context docker-desktop -n local get events --sort-by=.lastTimestamp
```

**B. "Restricted" is enforced.** A privileged pod, sent as a server-side dry run, must be refused with `violates PodSecurity "restricted:latest"`:

```sh
kubectl --context docker-desktop -n local run psa-test --dry-run=server --restart=Never \
  --image=localhost:5001/platform-verification-api:$TAG \
  --overrides='{"spec":{"containers":[{"name":"psa-test","image":"busybox","securityContext":{"privileged":true}}]}}'
```

**C. Service routing.** The Service lists two pod IPs:

```sh
kubectl --context docker-desktop -n local get endpointslices \
  -l kubernetes.io/service-name=local-platform-verification-api
```

Then a one-off client pod, which itself meets the "restricted" profile, calls the Service by name. Expect `200`, a request ID, and the identity response with the local release:

```sh
cat > /tmp/pva-local/svc-client.yaml <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: svc-client
  namespace: local
spec:
  restartPolicy: Never
  automountServiceAccountToken: false
  securityContext:
    runAsNonRoot: true
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: svc-client
      image: localhost:5001/platform-verification-api:$TAG
      command: ["python", "-c", "import urllib.request as u; r = u.urlopen('http://local-platform-verification-api/'); print(r.status, r.headers['x-request-id'], r.read().decode())"]
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop: ["ALL"]
EOF
kubectl --context docker-desktop apply -f /tmp/pva-local/svc-client.yaml
kubectl --context docker-desktop -n local wait --for=jsonpath='{.status.phase}'=Succeeded pod/svc-client --timeout=60s
kubectl --context docker-desktop -n local logs svc-client
kubectl --context docker-desktop -n local delete pod svc-client
```



### Clean up

Deleting the namespace removes everything the chart created. Stopping the registry keeps its images for next time; `docker rm -f local-registry` removes it entirely:

```sh
kubectl --context docker-desktop delete namespace local
docker stop local-registry
```



## Validating the chart

One command runs the application tests and every chart check, and prints `PASS` or `FAIL` for each:

```sh
platform/tests/validate-chart.sh
```

You need Helm, kubeconform (`brew install kubeconform`), and the application's virtual environment from [Testing the Python service](../apps/README.md#testing-the-python-service). The script runs from any directory in the repository.

What it checks:


| #   | Check           | Passes when                                                                                                                                                                         |
| --- | --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | App tests       | The pytest suite in `apps/platform-verification-api/` passes                                                                                                                        |
| 2   | Staging         | `values.yaml` + `values-staging.yaml` renders and passes kubeconform in strict mode, so unknown or misspelled fields fail                                                           |
| 3   | Local           | `values.yaml` + `values-local.yaml` renders and passes kubeconform in strict mode                                                                                                   |
| 4   | Invalid inputs  | Every file in `platform/charts/service/tests/fixtures/invalid/`, layered on the staging configuration, fails to render with the text on its first line. A failure names the fixture |
| 5   | Wrong namespace | Rendering into `default` is refused                                                                                                                                                 |


The five fixtures cover each way the chart rejects input: a missing field (`missing-owner`), a malformed value (`short-digest`), an unknown field (`unknown-key`), a name over 63 characters (`name-too-long`), and a request above its limit (`cpu-request-above-limit`).

Exit codes: `0` when every check passes, `1` when a check fails, and `2` when a tool is missing.

The Kubernetes schemas are pinned to version 1.36.4 (the `KUBERNETES_VERSION` variable in the script), matching the GKE cluster from my first lab session. The first run downloads the schemas into `~/.cache/kubeconform`, so it needs internet access; later runs use the cache. Set `KUBECONFORM_CACHE` to use a different directory.

To add an invalid fixture, create a small values file in `platform/charts/service/tests/fixtures/invalid/` that changes one input, and make its first line `# expect: <text the error must contain>`. Match a short, stable part of the message, such as the field path.

A passing run ends with:

```text
5 passed, 0 failed
```



## Testing the Helm chart

To see what the chart produces, render it. Combine the shared `values.yaml` with exactly one environment file, and pass the namespace that matches `environment`; the chart derives the namespace from `environment` and refuses to render into any other.

Staging:

```sh
helm template platform-verification-api platform/charts/service \
  -f platform/services/platform-verification-api/values.yaml \
  -f platform/services/platform-verification-api/values-staging.yaml \
  --namespace staging
```

Local:

```sh
helm template platform-verification-api platform/charts/service \
  -f platform/services/platform-verification-api/values.yaml \
  -f platform/services/platform-verification-api/values-local.yaml \
  --namespace local
```

Add `--show-only templates/service.yaml` to render one template. Rendering does not check the output against the Kubernetes API schema, and Helm 4 lint skips the chart's `fail` checks, so use the [validation script](#validating-the-chart) to test changes.

## Chart inputs

`[charts/service/values.schema.json](charts/service/values.schema.json)` enforces these rules during lint and rendering. The chart's templates check the combined name length and that requests are not above limits during rendering.


| Key                                                    | Required      | Rule                                                         |
| ------------------------------------------------------ | ------------- | ------------------------------------------------------------ |
| `project`                                              | Yes           | Lowercase letters, digits, and hyphens; starts with a letter |
| `environment`                                          | Yes           | `local` or `staging`                                         |
| `serviceName`                                          | Yes           | Same format as `project`                                     |
| `owner`                                                | Yes           | Kubernetes label value                                       |
| `image.repository`                                     | Yes           | Registry host and path, without tag or digest                |
| `image.digest`                                         | Yes           | `sha256:` followed by 64 lowercase hexadecimal characters    |
| `releaseVersion`                                       | Yes           | Quoted text; Kubernetes label value                          |
| `containerPort`                                        | Yes           | Integer from 1024 to 65535                                   |
| `probes.liveness.path`                                 | Yes           | Starts with `/`                                              |
| `probes.readiness.path`                                | Yes           | Starts with `/`                                              |
| `resources.requests.cpu`, `resources.limits.cpu`       | Yes           | Millicores, such as `100m`; requests not above limits        |
| `resources.requests.memory`, `resources.limits.memory` | Yes           | Mebibytes, such as `128Mi`; requests not above limits        |
| `replicaCount`                                         | No, default 2 | Integer from 2 to 3                                          |


`environment` and `serviceName` together must produce a name of at most 63 characters. A service image must declare a numeric non-root user, because the chart requires non-root execution without setting a user ID.