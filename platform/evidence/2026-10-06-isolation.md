# Identity, secrets, and isolation

This report records the first [lab session](../../infra/README.md#sessions) with workload identity, mounted secrets, and namespace isolation: release C reading a Secret Manager secret through its own Kubernetes service account, inside a `staging` namespace with a quota, a limit range, default-deny network policies, and a read-only developer role. Each control was tested with an allowed and a refused case. Values come from command output captured during the session; anything that was not captured is listed under [Deviations and gaps](#deviations-and-gaps).

## Summary

| Requirement | Target | Result |
| --- | --- | --- |
| Argo CD deploys the service from Git and the running image matches Git | Running digest equals `values-staging.yaml` at the synced commit | **Pass** |
| Authorized secret access | The API's Pods mount the demo secret and report its label | **Pass** |
| Unauthorized secret access | A Pod with the API's service account cannot mount `staging-forbidden-demo` | **Pass**: `IAM_PERMISSION_DENIED` |
| Authorized Google API access | The API's service account reads the demo secret through the Secret Manager API | **Pass**: HTTP 200 |
| Unauthorized Google API access | The forbidden secret, the `default` service account, and the same service account name in another namespace are refused | **Pass**: HTTP 403 in all three cases |
| Network isolation | Clients in `staging` and in another namespace cannot reach the API | **Pass**: both timed out while their internet control connected |
| DNS for workloads | The API's Pods resolve names | **Fail**: fixed in [#15](https://github.com/Josephdara/gke-platform/pull/15); passed on 2026-10-07, see [Admission policies, chart 1.0.0, and HTTPS](2026-10-07-admission.md#network-and-external-access) |
| No internet egress from workloads | The API's Pods cannot open outbound connections | **Not run**; passed on 2026-10-07, see [Admission policies, chart 1.0.0, and HTTPS](2026-10-07-admission.md#network-and-external-access) |
| Developer access | Read-only in `staging`; no secrets, exec, port-forward, writes, or other namespaces | **Pass**, by impersonation |
| Resource defaults and maximum | The LimitRange applies defaults and rejects a container above 500m CPU | **Pass** |
| Pod quota | The 11th Pod in `staging` is refused | **Pass** |
| Secret rotation | A new valid version reaches every Pod without a restart | **Pass**: 60 s |
| Invalid secret version | Serving Pods keep the last valid value and stay ready | **Pass** |
| Secret value kept internal | The value never appears in responses or logs | **Pass** |
| Read attribution | Secret Manager audit logs name the workload identity | **Pass** for allowed reads; denied reads not checked |
| Teardown | No lab resources remain; persistent resources untouched | **Pass** |

## Environment

| Component | Version or setting |
| --- | --- |
| GKE | Standard, zonal `us-east4-b`, Regular channel; control plane and nodes `1.36.4-gke.1391000` |
| Node pool | 2 × `e2-standard-2` (autoscaling 2 to 3), private nodes, Dataplane V2, node metadata mode `GKE_METADATA` |
| Cluster DNS | kube-dns, with NodeLocal DNSCache on by GKE's default for Standard clusters from 1.34.1-gke.3720000 |
| Secret Manager add-on | Rotation every 120 seconds; CSI driver `secrets-store-gke.csi.k8s.io` requesting tokens for `gke-build-proj.svc.id.goog` |
| Argo CD | `quay.io/argoproj/argocd:v3.5.3@sha256:dd3f47d5a5e4da563a7a398506e892481b358a7cec50abdf320c71aa55904bfa`, core install |
| Helm bundled in Argo CD | `v4.2.1+gd591a19` |
| kubectl | 1.37.0 |
| Test Pods | Release C's image, run as user 10001 under Pod Security "restricted" |

## Revisions and images

| Commit | Pull request | Change |
| --- | --- | --- |
| `93efdc6272241f7ac5696549f66f8fdb74052791` | [#10](https://github.com/Josephdara/gke-platform/pull/10) | Secrets, the per-service grant, and Secret Manager audit logs; applied with the lab off |
| `4f848fc0c3fc506de904f7c228f5b19e658faafa` | [#12](https://github.com/Josephdara/gke-platform/pull/12) | The API reads a mounted secret (release C) |
| `608dee5a5ffb180bc872d890303ac89bee372f8a` | [#13](https://github.com/Josephdara/gke-platform/pull/13) | Chart `secrets[]` input |
| `3ba98972add79940a31aa8a729c2054e8229a9a0` | [#14](https://github.com/Josephdara/gke-platform/pull/14) | Staging guardrails and project changes, and the promotion to release C. Head of `main` at bootstrap |
| `cb3a907e5a35e336460685575aea4c89e6b414b8` | [#15](https://github.com/Josephdara/gke-platform/pull/15) | DNS fix, after the session |

| Release | Tag | Digest | Notes |
| --- | --- | --- | --- |
| C | `sha-4f848fc` | `sha256:5eefe9ae99fadc5b0837e468a38acd83bcd386a586b3da85d8a1f011caf60aa3` | Published by build `894a74b1`, with status `SUCCESS` |

The demo secret `staging-platform-verification-api-demo` held version 1 (label `v1`) at the start of the session. Versions 2 and 3 were added during the rotation test. The forbidden secret `staging-forbidden-demo` has no grants.

## Checks before the session

| Check | Result |
| --- | --- |
| `validate-chart.sh` on the content merged in [#14](https://github.com/Josephdara/gke-platform/pull/14) | 5 passed, 0 failed: 55 application tests, 6 invalid fixtures rejected, wrong namespace refused. The staging render had 5 resources; kubeconform skipped the SecretProviderClass |
| kubeconform on `platform/cluster/` and `platform/argocd/root/` | 7 valid; 4 Argo CD resources skipped |
| kube-dns | 2 Pods Running |
| Secret Manager add-on | CSI driver and SecretProviderClass CRD present |

## Bootstrap

`bootstrap.sh` ended with `PASS  running image matches Git`. The synced revision was `3ba98972add79940a31aa8a729c2054e8229a9a0`, and the running digest equalled release C's.

| Root `staging-platform` | Service `staging-platform-verification-api` |
| --- | --- |
| `Unknown/Unknown` (2 polls) | not created yet |
| `OutOfSync/Missing` (2 polls) | not created yet |
| `Synced/Progressing` | `Synced/Progressing` |
| `Synced/Healthy` | `Synced/Healthy` |

After the sync, `staging` held the ResourceQuota, the LimitRange, both NetworkPolicies, the Role, the RoleBinding, and the service's SecretProviderClass. Quota use at rest was 2 of 10 Pods, 200m of 1 CPU and 256Mi of 1Gi requested, and 1 of 3 CPU and 512Mi of 2Gi in limits. The two API Pods ran on different nodes; each pulled the 50,677,917-byte image in under 5 seconds and logged `secret_loaded` with label `v1`, 1 second apart.

## Test setup

- A namespace `isolation-check`, with a service account named `staging-platform-verification-api`, the same name as the API's.
- A temporary NetworkPolicy, `check-egress`, that allowed all egress for test Pods labelled `check: egress` in `staging`. A refused connection to the API therefore came from the API's ingress rules, not from the client's own egress.
- One-shot test Pods running release C's image, which printed only HTTP status codes or connection results, never a secret value or token.

All three were deleted before teardown.

## Test results

| # | Area | Test | Expected | Actual | Result |
| --- | --- | --- | --- | --- | --- |
| 1 | Secret | `/` on each API Pod, through `kubectl exec` | `secretLabel: v1`, version `sha-4f848fc` | Both Pods returned exactly that | Pass |
| 2 | Secret | `SECRET_FILE` in the ConfigMap | Path in the chart's mount directory | `/var/secrets/staging-platform-verification-api-demo` | Pass |
| 3 | Secret | Mounted file read by user 10001 | Readable without `fsGroup` | A symlink into `..data/`, owned by root, read by the app at startup | Pass |
| 4 | Secret | Logs | One `secret_loaded` per Pod; no value field | 2 `secret_loaded` lines; 0 lines containing `"value"` | Pass |
| 5 | Secret | Pod with the API's service account mounting `staging-forbidden-demo` | Mount refused | `ContainerCreating` after 65 s; `FailedMount` with `PermissionDenied`, `Permission 'secretmanager.versions.access' denied`, reason `IAM_PERMISSION_DENIED` | Pass |
| 6 | Google API | API's service account reading the demo secret | 200 | 200 | Pass |
| 7 | Google API | API's service account reading the forbidden secret | 403 | 403 | Pass |
| 8 | Google API | `default` service account in `staging` reading the demo secret | 403 | 403 | Pass |
| 9 | Google API | Same service account name in `isolation-check` reading the demo secret | 403 | 403 | Pass |
| 10 | Network | Client in `staging` to the API's Service on port 80 | Refused | `TimeoutError`; control `www.google.com:443` connected | Pass |
| 11 | Network | Client in `isolation-check` to the API's Service on port 80 | Refused | `TimeoutError`; control `www.google.com:443` connected | Pass |
| 12 | Network | DNS lookup from an API Pod | Resolves | `socket.gaierror: Temporary failure in name resolution` | Fail |
| 13 | Network | Outbound connection from an API Pod | Refused | Not reached: test 12 stopped the script | Not run |
| 14 | LimitRange | Test Pod without resource settings | Requests 50m and 64Mi, limits 200m and 128Mi | Exactly those values | Pass |
| 15 | LimitRange | Container with a 1 CPU limit, server dry run | Refused | `maximum cpu usage per Container is 500m, but limit is 1` | Pass |
| 16 | Quota | Deployment of 9 Pods next to the 2 API Pods | One Pod refused | `pods: 10/10`; `exceeded quota: staging-quota, requested: pods=1, used: pods=10, limited: pods=10` | Pass |
| 17 | RBAC | 13 permissions, impersonating group `staging-developers` | See below | See below | Pass |
| 18 | RBAC | `list pods` in `argocd`, `default`, and `kube-system` | `no` | `no` in all three | Pass |

Test 17, as `kubectl auth can-i` answered:

| Permission in `staging` | Answer |
| --- | --- |
| `get pods`, `get pods/log`, `list events`, `list events.events.k8s.io`, `list deployments.apps`, `list services`, `list configmaps` | `yes` |
| `get secrets`, `create pods/exec`, `create pods/portforward`, `create pods`, `patch deployments.apps`, `delete configmaps` | `no` |

## Rotation

Version 2 was deliberately invalid: a label containing a space and an empty value.

| Since the first failure | Observation |
| --- | --- |
| 0 | First Pod logged `secret_reload_failed` with `error_type: SecretFormatError` |
| +4 s | Second Pod logged the same |
| +1 min 53 s to +5 min 25 s | 12 samples of both Pods' labels, all `v1` |

Both Pods stayed `1/1` Ready with 0 restarts. Version 3, a valid secret with label `v3`, reached every Pod 60 seconds after it was added, measured from just before the `gcloud secrets versions add` command. Version 2 was then disabled, leaving versions 1 and 3 enabled.

The driver checks each Pod's mount on its own 120-second cycle, so the time for a version to reach every Pod depends on where in each cycle it lands. The application rereads the file on its next `/` or `/readyz` request, and readiness probes call `/readyz` every 5 seconds.

## Audit log

The 20 most recent `AccessSecretVersion` entries, spanning 12 min 53 s, all name the principal `serviceAccount:gke-build-proj.svc.id.goog[staging/staging-platform-verification-api]` reading `projects/PROJECT_NUMBER/secrets/staging-platform-verification-api-demo/versions/latest`, with no error status. No test Pod ran in that window, so these reads came from the CSI driver's rotation checks. Entries for the refused reads in tests 5, 7, 8, and 9 fell outside these 20 rows and were not queried.

## DNS failure

The API Pod could not resolve any name. The cluster had NodeLocal DNSCache enabled: GKE turns it on by default for Standard clusters from 1.34.1-gke.3720000, and the Terraform does not set it. With Dataplane V2, the cache runs as ordinary Pods in `kube-system`, and a Pod's DNS queries go to the cache Pod on its own node. `staging-allow-dns` only allowed Pods labelled `k8s-app: kube-dns`, so those queries were dropped.

The test clients in tests 10 and 11 resolved names because the temporary `check-egress` policy allowed them all egress, so the failure appeared only on the API Pod. The API itself needs no DNS today, but every future workload in `staging` would have failed name lookups.

The fix, [#15](https://github.com/Josephdara/gke-platform/pull/15), changed `staging-allow-dns` to allow port 53, UDP and TCP, to any Pod in `kube-system`, which covers both kube-dns and the cache. The change had not run on a cluster when this report was written; it passed on 2026-10-07, see [Admission policies, chart 1.0.0, and HTTPS](2026-10-07-admission.md#network-and-external-access).

## Teardown

Automated sync was turned off on the root Application and then the service Application. No LoadBalancer Services or Gateways existed. A saved `lab_enabled=false` plan destroyed 6 resources: the node pool took 4 min 22 s, the cluster 5 min 2 s, the subnet 21 s, and the network 23 s, with the NAT and router removed during the node pool's deletion. The inventory of clusters, instances, disks, addresses, forwarding rules, network endpoint groups, routers, networks, and firewall rules was empty. A final plan reported `No changes` with exit code 0; the secrets, the grant, and the audit configuration were untouched.

Creating the lab took 9 min 13 s of Terraform time.

## Deviations and gaps

| Item | What happened | Effect |
| --- | --- | --- |
| DNS from workloads | Failed, as described above | Fixed in [#15](https://github.com/Josephdara/gke-platform/pull/15); passed on 2026-10-07, see [Admission policies, chart 1.0.0, and HTTPS](2026-10-07-admission.md#network-and-external-access) |
| Workload internet egress | Test 13 did not run because test 12 stopped the script | Unverified here; passed on 2026-10-07, see [Admission policies, chart 1.0.0, and HTTPS](2026-10-07-admission.md#network-and-external-access) |
| Invalid version timing | The time version 2 was added was not captured | Only its reload failures are recorded, not its propagation time |
| Denied reads in the audit log | Not queried | Attribution is shown for allowed reads only |
| Release C evidence | The evidence bucket listing was not captured in this session | The pipeline pushes only after its evidence upload succeeds |
| Promotion | Release C was promoted inside [#14](https://github.com/Josephdara/gke-platform/pull/14), together with the guardrails | Rolling back the release alone needs a new pull request, not a revert of [#14](https://github.com/Josephdara/gke-platform/pull/14) |
| Bootstrap duration | Not timed | |
| Capacity | Node usage and requests were not recorded | Quota use is recorded instead |
| RBAC | Tested by impersonation only; Google Groups for RBAC is not configured | The rules are proven, not a real developer sign-in |

## Follow-ups

- At the start of the next session, rerun the DNS lookup and outbound connection from an API Pod: expect a resolved address, then a timeout.
- Optional hardening: the cluster allows RBAC bindings to `system:authenticated` and `system:unauthenticated` (GKE's default); a Terraform setting can forbid them.
- Optional: set NodeLocal DNSCache explicitly in Terraform, so the DNS policy's dependency is visible in code.
- Revisit the quota when the HPA arrives.
- Time the bootstrap and record the time of each secret version change in future sessions.
