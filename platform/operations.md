# Operations

This is how I investigated an unhealthy service and took a node out for maintenance on the staging lab cluster. Every command here ran in a lab session on 2026-10-07, and the timings come from that session; see the [evidence report](evidence/2026-10-07-acceptance.md). Run the commands from the repository root, during a lab session, after the bootstrap.

Set these once in each terminal:

```bash
C=gke_gke-build-proj_us-east4-b_staging-super-cluster; APP=staging-platform-verification-api; URL=https://api.staging.gke.josephdara.com/
```

`pq` runs a PromQL query against Managed Service for Prometheus with your gcloud credentials and prints each series with its value:

```bash
pq() { curl -s -G "https://monitoring.googleapis.com/v1/projects/gke-build-proj/location/global/prometheus/api/v1/query" -H "Authorization: Bearer $(gcloud auth print-access-token)" --data-urlencode "query=$1" | python3 -c 'import json,sys; d=json.load(sys.stdin); [print(r["metric"], r["value"][1]) for r in d.get("data",{}).get("result",[])] or print(d)'; }
```



## Investigating an unhealthy service



### Alerts

Terraform creates these with the lab and removes them at teardown. They email the `staging-alerts` channel; see [Alert email channel](../infra/README.md#alert-email-channel).


| Alert                       | Severity | Fires when                                                                                                               |
| --------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------ |
| `staging-no-ready-replicas` | Critical | A `staging-*` Deployment has had no available replicas for 2 minutes                                                     |
| `staging-error-rate`        | Warning  | More than 1% of a service's requests returned a 5xx status for 5 minutes, while it handled at least 1 request per second |
| `staging-latency`           | Warning  | A service's p95 latency stayed above 500 ms for 5 minutes                                                                |


The email names the policy, the Deployment or service, and the value that crossed the threshold, followed by the alert's description. When the API lost its last replica, the email arrived 3 to 4 minutes later, and a recovery email 5 to 6 minutes after the Pods were ready again. The subject ends in `on __missing__`, because a PromQL alert has no monitored resource to name.

The error-rate and latency alerts read the API's own metrics, so they miss errors the load balancer returns by itself, such as a 503 while no Pod is ready. Check from outside as well:

```bash
curl -s -o /dev/null -w "HTTPS %{http_code}\n" $URL
```



### 1. Check the platform

```bash
platform/tests/live-checks.sh
```

A failing check names the layer: Argo CD, the running image, the secret, the network, admission, developer access, or HTTPS. In the first few minutes after a bootstrap, HTTPS can return 404 while the load balancer is still being programmed.

### 2. Look at the Pods and recent events

```bash
kubectl --context $C -n staging get pods -l app.kubernetes.io/instance=$APP -o wide
```

```bash
kubectl --context $C -n staging get events --sort-by=.lastTimestamp | tail -n 15
```

Probe failures, mount failures, and `LoadBalancerNegNotReady`, which means the load balancer has not yet marked a new Pod healthy, show up in the events.

### 3. Read the metrics

Which Pods the collectors reach, and the release each one runs:

```bash
pq 'up{namespace="staging"}'
```

Requests over the last 10 minutes, by release, route, and status:

```bash
pq 'sum by (version, route, status) (increase(http_requests_total{namespace="staging"}[10m]))'
```

The API's own p95 latency over the last 10 minutes, in seconds:

```bash
pq 'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{namespace="staging"}[10m])))'
```

Every series carries `version`, copied from the Pod's `app.kubernetes.io/version` label. That is the `releaseVersion` in `values-staging.yaml`, `sha-` followed by the commit the image was built from, so a problem that starts with a new `version` points at that release. Under load, the API's own p95 stayed at or below 5 ms while clients over the internet saw 40 to 60 ms, so a high client latency with a low API latency points at the network or the load balancer.

### 4. Recover

If the problem started with a release, revert its promotion pull request, as in [Releasing and rolling back](README.md#releasing-and-rolling-back). Argo CD deploys the previous digest without a rebuild.

Argo CD does not manage the replica count, and the autoscaler does nothing while a Deployment is at 0. A Deployment scaled to 0 by hand stays there until you scale it back:

```bash
kubectl --context $C -n staging scale deployment $APP --replicas=2; kubectl --context $C -n staging rollout status deployment $APP --timeout=3m
```



## Node maintenance



### Before you start

The control plane and node versions:

```bash
gcloud container clusters describe staging-super-cluster --zone=us-east4-b --project=gke-build-proj --format="value(currentMasterVersion,currentNodeVersion)"
```

The disruption budget must allow 1 disruption:

```bash
kubectl --context $C -n staging get pdb,hpa
```

Then run the live checks.

### Draining a node

Pick a node; this picks the one running the first API Pod:

```bash
NODE=$(kubectl --context $C -n staging get pods -l app.kubernetes.io/instance=$APP -o jsonpath='{.items[0].spec.nodeName}'); echo $NODE
```

```bash
kubectl --context $C drain $NODE --ignore-daemonsets --delete-emptydir-data --timeout=8m
```

What to expect, from a drain under 20 requests per second:

- The drain finished in 35 seconds. It also evicted kube-dns, Argo CD, and Kyverno's cleanup and reports controllers, which restarted elsewhere.
- The evicted API Pod's replacement was serving through the load balancer about 30 seconds after it was scheduled, while the other API Pod kept serving.
- Two nodes cannot hold everything, so the cluster autoscaler added a third node within about 70 seconds.
- 53 of 12,000 requests got a 503 from the load balancer.

Admission in `staging` fails closed. If the Kyverno admission controller runs on the drained node, no new Pod can start in `staging` until it is running again; I have not tested that case.

When the work on the node is done:

```bash
kubectl --context $C uncordon $NODE
```

About 10 minutes later, the autoscaler removed the emptiest node. Run the live checks again. After a drain, both API replicas can end up on the same node, because the chart sets no spreading rule.

### Upgrades

I have not rehearsed a node upgrade. `gcloud container clusters upgrade staging-super-cluster --zone=us-east4-b --project=gke-build-proj --node-pool=staging-super-pool` without a version upgrades the nodes to the control plane's version; when they already run it, the command prints `done` after a few seconds and replaces nothing.