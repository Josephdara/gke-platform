# Observability and acceptance tests

This report records the first [lab session](../../infra/README.md#sessions) with metrics and email alerts, and the platform's acceptance tests: steady load through the Gateway, autoscaling under higher load, a Pod failure, a voluntary node drain, and a node maintenance rehearsal, each with traffic running. The API ran release D, the first release that serves Prometheus metrics. Times are durations, or elapsed from the start of each test. Values come from command output captured during the session and from a watcher that logged the API's Pods, the autoscaler, and the nodes every 5 seconds; anything that was not captured is listed under [Deviations and gaps](#deviations-and-gaps).

## Summary

The targets for active tests come from [architecture.md](../../architecture.md#observability): 99% successful requests and p95 latency below 500 ms. A successful request is one that returned HTTP 200; requests still in flight when a load run's timer ended are not counted.

| Requirement | Target | Result |
| --- | --- | --- |
| Argo CD deploys release D and the running image matches Git | Running digest equals `values-staging.yaml` at the synced commit | **Pass** |
| Managed Prometheus scrapes the API | Both Pods report `up` = 1, labelled with their release | **Pass**: `version` = `sha-d1b3f48` |
| Only the collectors reach the metrics port | A Pod in another namespace is refused | **Pass** |
| Alert delivery | An email when the API has no ready replicas | **Pass**: 3 to 4 minutes after the last replica went |
| Steady load | 20 requests per second for 10 minutes | **Pass**: 99.78%, p95 56 ms |
| Autoscaling | The HPA adds a replica above 70% CPU | **Pass**: 2 to 3 replicas at 150 requests per second |
| Pod failure | A replacement becomes ready; at least 99% successful | **Pass**: ready in 22 s, 99.22% |
| Voluntary node drain | The PDB is respected and the replacement serves; at least 99% successful | **Pass**: 99.56% |
| Node maintenance rehearsal | Nodes replaced under load, then the workload validated | **Open**: no node was replaced |
| Live checks | All 9 pass before and after the disruption tests | **Pass**, once the load balancer finished programming |
| Teardown | No lab or load balancer resources remain; persistent resources untouched | **Pass** |

## Environment

| Component | Version or setting |
| --- | --- |
| GKE | Standard, zonal `us-east4-b`, Regular channel; control plane and nodes `1.36.4-gke.1391000` |
| Node pool | 2 × `e2-standard-2` (autoscaling 2 to 3), surge upgrades with 1 extra node and none unavailable |
| Monitoring | Managed Service for Prometheus with managed collection: a collector on each node and `gmp-operator` in `gmp-system`; GKE's Deployment kube state metrics in `gke-managed-cim` |
| Argo CD | 3.5.3 core install from `staging-mirror`, bundled Helm `v4.2.1+gd591a19` |
| Kyverno | 1.19.1 from `staging-mirror`; policies in Deny |
| Chart | `service` 1.1.0, with `metrics.port: 9090` |
| Load client | `oha` 1.16.0 on macOS, calling `https://api.staging.gke.josephdara.com/` over the internet |

## Revisions

| Commit | Pull request | Change |
| --- | --- | --- |
| `d8b158d290d81d542d3948ee932dce6c270016cf` | [#23](https://github.com/Josephdara/gke-platform/pull/23) | Chart, policy, and Terraform checks in pull request CI, and the live-check script |
| `d1b3f489e4d39da6c477b3e225c49a29b89cd4ac` | [#24](https://github.com/Josephdara/gke-platform/pull/24) | Prometheus request metrics in the API: the source of release D |
| `a59d527067956f4a47b050aea308c6da67a80eec` | [#25](https://github.com/Josephdara/gke-platform/pull/25) | Managed Prometheus and alerts in Terraform, chart 1.1.0, and the promotion to release D. Head of `main` at bootstrap |

## Release D

| Field | Value |
| --- | --- |
| Tag | `sha-d1b3f48` |
| Digest | `sha256:daba5ff446f0051d31c31e6ae29fcbcc8e5d70ae81b74e312a9612656378b7b0`, the same in the build result and the registry |
| Build | `547fe0c4-0655-44e9-b236-20f54e615877`, trigger `staging-main-publish`, status `SUCCESS` for commit `d1b3f489e4d39da6c477b3e225c49a29b89cd4ac` |
| Evidence | `scan.json` and `sbom.cdx.json` under `gs://gke-build-proj-staging-build-evidence/platform-verification-api/d1b3f489e4d39da6c477b3e225c49a29b89cd4ac/` |
| Provenance | Names the commit as `gitCommit`, `COMMIT_SHA`, and `REVISION_ID`, the trigger `staging-main-publish`, and the evidence folder |

This closes the gap left by the two previous reports, where the evidence listing for the running release was not captured.

## Bootstrap

A saved plan created 11 resources, including the 3 alert policies and a cluster with managed Prometheus enabled. The cluster took 7 min 59 s and the node pool 1 min 22 s. The bootstrap started 72 minutes after the apply finished and took 9 min 28 s, ending with `PASS  running image matches Git` at revision `a59d527` and release D's digest.

Both Applications reported `Synced/Degraded` in three polls spanning 11 s, about a minute before the bootstrap ended, before settling at `Synced/Healthy`, as during the [admission session's bootstrap](2026-10-07-admission.md#bootstrap). A health log polled every 5 seconds recorded no unhealthy resource at that moment, because Argo CD 3.x does not keep each resource's health in the Application's status by default, so the cause was again not captured. The likely cause is the HorizontalPodAutoscaler: Argo CD reports an HPA as Degraded while it cannot read CPU metrics for new Pods, and the state first appeared when chart 1.0.0 added the HPA.

## Live checks

| When | Result |
| --- | --- |
| 2 min 13 s after the bootstrap | 8 passed, 1 failed: HTTPS returned 404 |
| 5 min 39 s after the bootstrap | 9 passed |
| After all disruption tests | 9 passed, on 2 nodes |

The 404 came from the new global load balancer, which was still programming its route; nothing in the cluster changed between the two runs.

## Capacity

| Node | CPU requests | Memory requests |
| --- | --- | --- |
| `…-grm2` | 1271m (65%) | 36% |
| `…-tlk6` | 1509m (78%) | 43% |

The [admission session](2026-10-07-admission.md#hpa-pdb-and-capacity) earlier that day, without managed Prometheus, recorded 1260m (65%) and 1404m (72%). The additions are two collectors, `gmp-operator`, and `kube-state-metrics`. No Pod was Pending.

## Metrics

| Check | Result |
| --- | --- |
| PodMonitoring | `ConfigurationCreateSuccess=True` |
| `up{namespace="staging"}` | 1 for both API Pods, with `job`, `pod`, `container`, and `version` = `sha-d1b3f48`; managed collection also adds `top_level_controller_type` = `Deployment` |
| Requests counted by the API, after the steady load run | One series: route `/`, status `200`, release `sha-d1b3f48`. The API counted no 404 or 503 |
| The API's own p95 over 10 minutes | `0.005`, the histogram's lowest bucket, so at most 5 ms |
| A Pod in another namespace to an API Pod's IP on port 9090 | `metrics blocked TimeoutError`, while its control connection printed `internet connected` |

## Alert delivery

The Deployment was scaled to 0 by hand. Neither Argo CD nor the autoscaler restored it: Git sets no replica count, and the HPA does not act on a Deployment at 0.

| Since the scale-down | Event |
| --- | --- |
| 0 | Scaled to 0 |
| 17 s | No API Pods left |
| 51 s | HTTPS returned 503 |
| 3 min 19 s to 4 min 18 s | Email received: `[ALERT - No severity] staging-no-ready-replicas on __missing__`, with the Deployment name, the value 0, and the policy's description |
| 5 min 41 s | Scaled back to 2 |
| 5 min 56 s | Rollout complete; HTTPS returned 200 |
| 11 min 15 s to 12 min 14 s | Recovery email, reporting an incident of 7 min 56 s |

The email named the metric `kubernetes.io/anthos/kube_deployment_status_replicas_available/gauge`; the alert's PromQL uses `kube_deployment_status_replicas_available`. "No severity" reflected policies without a severity, which has since been added to the alert configuration. `__missing__` is where a resource name would appear; a PromQL condition has none.

## Load and autoscaling

| Run | Responses | 200 | Other | Successful | p95 | p99 | Slowest |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Steady: 20 per second for 10 min | 12,000 | 11,974 | 17 × 404, 9 × 503 | 99.78% | 56 ms | 111 ms | 0.57 s |
| Autoscaling: 150 per second for 6 min | 53,995 | 53,928 | 67 × 503 | 99.88% | 42 ms | 63 ms | 1.09 s |

Latencies are measured at the client and include about 30 ms of network round trip; the API's own p95 was at most 5 ms.

At 20 requests per second, the 2 Pods averaged 34% to 39% of their 100m CPU request. At 150 requests per second, CPU reached 54%; 6 s later the HPA was running 3 replicas at 125%, and the third Pod was ready 18 s after that first high reading. CPU peaked at 213% 36 s after it and stayed near 140% on 3 replicas, the maximum, until the load stopped. The latency target still held, because each Pod may use up to its 500m limit. The HPA returned to 2 replicas about 5 minutes after the load stopped.

## Pod failure

With 20 requests per second running, one API Pod was force-deleted with a grace period of 0. Its replacement was created at once and was ready 22 s later.

| Responses | 200 | Other | Successful | p95 | Slowest |
| --- | --- | --- | --- | --- | --- |
| 6,000 | 5,953 | 47 × 503 | 99.22% | 47 ms | 5.09 s |

30 requests took about 5 seconds. The load balancer kept sending requests to the deleted Pod until its endpoint was removed.

## Voluntary node drain

With 20 requests per second running, the node `…-tlk6`, which held one API Pod, was drained in 35 s. The drain evicted 9 Pods: the API Pod, kube-dns, a konnectivity agent, all four Argo CD components, and Kyverno's cleanup and reports controllers. The Kyverno admission controller ran on the other node, so admission in `staging` stayed available.

- The API Pod's replacement was scheduled on `…-grm2`, where the other API Pod kept serving. Its container started 9 seconds later, and 29 seconds after scheduling the load balancer marked it healthy (`LoadBalancerNegReady`).
- The cluster autoscaler added a third node, `…-vp7j`, which registered 53 s after the drain began and was Ready 1 min 11 s after it.
- `…-tlk6` was uncordoned 4 min 38 s after the drain began.

No Pod stayed Pending, apart from a collector initializing on the new node.

| Responses | 200 | Other | Successful | p95 | Slowest |
| --- | --- | --- | --- | --- | --- |
| 12,000 | 11,947 | 53 × 503 | 99.56% | 55 ms | 5.03 s |

19 requests took about 5 seconds. After the drain, both API Pods ran on `…-grm2` until teardown. 10 min 42 s after the uncordon, the autoscaler cordoned `…-tlk6` and removed it 1 min 54 s later; which had held no API Pod since the drain.

## Node maintenance rehearsal

Prechecks: control plane and nodes both at `1.36.4-gke.1391000`, the PDB allowing 1 disruption, and the HPA at 5% with 2 replicas.

`gcloud container clusters upgrade staging-super-cluster --node-pool=staging-super-pool` ran without a version, which upgrades the nodes to the control plane's version. It printed `done` after 12 s. The nodes were the same afterwards: `…-grm2` and `…-tlk6` were 153 minutes old and `…-vp7j` 13 minutes. Because the nodes already ran that version, no node was replaced, and the rehearsal did not happen. This gate stays open until a newer version is available to upgrade to.

The 25-minute load run that covered the attempt:

| Responses | 200 | Other | Successful | p95 | Slowest |
| --- | --- | --- | --- | --- | --- |
| 30,000 | 29,974 | 24 × 503, 1 × 504, 1 read error | 99.91% | 43 ms | 30.0 s |

Both API Pods stayed on `…-grm2`, unchanged, for the whole run; the only change in the cluster was the autoscaler removing `…-tlk6`. The live checks afterwards passed.

## Findings

1. **The load balancer returns a small number of 503s even when nothing changes.** In the maintenance run, no API Pod changed for 25 minutes, and there were still 24 × 503, a 504 after 30 seconds, and a read error; the steady and autoscaling runs show similar rates. The API counted only 200s. Request logging on the load balancer is off, so the cause is not confirmed. A likely cause is that the API closes idle connections after Uvicorn's default 5 seconds, while Google's load balancer expects backends to keep them open for longer than its own 600 seconds.
2. **Each disruption cost about 50 requests.** The Pod failure lost 47, as expected for an abrupt kill. The drain lost 53 even though eviction is graceful, which suggests the Pod stops serving before the load balancer removes it. A `preStop` delay or connection draining on the backend would close that gap.
3. **Both replicas ended on one node.** The chart sets no spreading rule, so after the drain both API Pods ran on `…-grm2`. Losing that node would have stopped the service until replacements started.
4. **Two nodes cannot absorb the loss of one.** The drain needed a third node, which the autoscaler added within about 70 seconds.
5. **The alerts see only what the API sees.** The 503s in finding 1, and every 503 while no Pod was ready, never reached the API, so the error-rate alert cannot fire on them. The zero-replicas alert, built on kube state metrics, covers a full outage.
6. **HTTPS needs a few minutes after the bootstrap.** It returned 404 two minutes after the bootstrap and 200 six minutes after.

## Teardown

Automated sync was turned off on the root Application and then the service Application, and the HTTPRoute and Gateway were deleted. The wait for all five load balancer resource types ended, and no LoadBalancer Services or Gateways remained. A saved `lab_enabled=false` plan destroyed 11 resources: the 3 alert policies in 1 to 2 seconds, the static IP and the A record, the node pool in 4 min 22 s, the cluster in 6 min 53 s, the router and NAT, the subnet in 21 s, and the network in 24 s. During the node pool's deletion, the watcher saw a new node register as NotReady; it went with the pool. The inventory of 13 resource types was empty, and a final plan reported `No changes` with exit code 0.

## Deviations and gaps

| Item | What happened | Effect |
| --- | --- | --- |
| Node maintenance rehearsal | The node pool upgrade was a no-op because the nodes already ran the control plane's version | Open: no upgrade has been rehearsed |
| Transient `Degraded` | Seen in three polls spanning 11 s; the health log could not see resource health | Likely the HPA before its first metrics; not confirmed |
| Load balancer 503s | Load balancer request logging is off | Cause not confirmed |
| First live-check run | HTTPS returned 404 before the load balancer was ready; the rerun 3 min 26 s later overwrote its log file | The failing run is recorded from terminal output |
| Request counts from the API | The query ran after the steady run, and its 10-minute window covered only part of it | The count is not the run's total; the status codes are still complete for that window |
| The API's p95 | 5 ms is the histogram's lowest bucket | Only an upper bound |
| Pause before the bootstrap | 72 minutes passed between creating the lab and bootstrapping it | Billed idle cluster time |
| Alert email times | The emails show minutes only | Firing and recovery times are ranges of up to a minute |
| Teardown end | The time the final destroy finished was not recorded | The lab existed for about three and a half hours |
| Cost | Billing data for the day had not settled | Reported separately |

## Follow-ups

- Set Uvicorn's keep-alive above 600 seconds and turn on load balancer logging for the service, then rerun the steady load to see whether the 503s stop.
- Add a `preStop` delay or backend connection draining, and rerun the drain.
- Add a topology spread constraint to the chart so replicas prefer different nodes.
- Rehearse a node pool upgrade when the Regular channel offers a newer version than the cluster runs.
- Find a way to capture each resource's health during the bootstrap, so the transient `Degraded` can be confirmed.
