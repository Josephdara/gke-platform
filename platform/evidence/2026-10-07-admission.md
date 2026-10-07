# Admission policies, chart 1.0.0, and HTTPS

This report records the first [lab session](../../infra/README.md#sessions) with Kyverno admission control, controller images from the mirror repository, chart 1.0.0 with an HPA and PDB, and external HTTPS through a Gateway on `api.staging.gke.josephdara.com`. The policies ran in Audit mode first and were switched to Deny during the session. It also reruns the two network checks left open on 2026-10-06; see [Identity, secrets, and isolation](2026-10-06-isolation.md#dns-failure). All times are UTC on 2026-10-07 unless stated. Values come from command output captured during the session; anything that was not captured is listed under [Deviations and gaps](#deviations-and-gaps).

## Summary

| Requirement | Target | Result |
| --- | --- | --- |
| Argo CD deploys the service from Git and the running image matches Git | Running digest equals `values-staging.yaml` at the synced commit | **Pass**, on the second bootstrap; the first failed and was fixed in [#22](https://github.com/Josephdara/gke-platform/pull/22) |
| Controller images come from the mirror | Every Argo CD, Redis, and Kyverno image from `staging-mirror`, by digest | **Pass** |
| Kyverno runs on the cluster's Kubernetes version | Controllers Running and all 7 policies ready on 1.36 | **Pass** |
| Admission fails closed for application namespaces only | Policy webhook with `failurePolicy: Fail`, scoped to `staging` | **Pass** |
| Audit phase shows the running workloads pass | 0 failures in the policy reports | **Pass** |
| Every policy rejects its failing fixture, with a message naming the field and fix | 7 of 7 denied under Deny; the compliant Deployment accepted | **Pass** |
| Policies do not affect other namespaces | The same non-compliant Deployment admitted in `default` | **Pass** |
| HPA and PDB present | HPA 2 to 3 replicas at 70% CPU; PDB `minAvailable: 1` | **Pass** |
| HTTPS on the delegated subdomain | `https://api.staging.gke.josephdara.com/` returns 200 with a Google-issued certificate | **Pass** |
| Only the load balancer reaches the API | A Pod in another namespace is refused | **Pass** |
| DNS for workloads (failed on 2026-10-06) | The API's Pods resolve names | **Pass**: the fix in [#15](https://github.com/Josephdara/gke-platform/pull/15) works |
| No internet egress from workloads (not run on 2026-10-06) | The API's Pods cannot open outbound connections | **Pass** |
| Teardown | No lab or load balancer resources remain; persistent resources untouched | **Pass**, after a wait-loop gap described below |

## Environment

| Component | Version or setting |
| --- | --- |
| GKE | Standard, zonal `us-east4-b`, Regular channel; control plane and nodes `1.36.4-gke.1391000` |
| Node pool | 2 × `e2-standard-2` (autoscaling 2 to 3), private nodes, Dataplane V2, NodeLocal DNSCache |
| Cluster RBAC | Bindings to `system:authenticated` and `system:unauthenticated` forbidden |
| Argo CD | 3.5.3 core install from `staging-mirror`, bundled Helm `v4.2.1+gd591a19` |
| Kyverno | 1.19.1 from `staging-mirror`: admission, background, cleanup, and reports controllers |
| Gateway | `gke-l7-global-external-managed`, HTTPS on 443, certificate map `staging-cert-map`, address `staging-gateway-ip` |

## Revisions

| Commit | Pull request | Change |
| --- | --- | --- |
| `dd89f7be59cca73f2d6d7e6fa12d941dc54f275e` | [#18](https://github.com/Josephdara/gke-platform/pull/18), merged 2026-10-06 21:39:00 | DNS zone, certificate, mirror repository, cluster hardening |
| `0b597dd0c18b83a48117cb934d09d44e4860c519` | [#19](https://github.com/Josephdara/gke-platform/pull/19), merged 2026-10-06 22:39:51 | Kyverno, mirrored images, policies in Audit |
| `d21cf26a9bd0aa04194234ac3fd4ea7c58074b38` | [#20](https://github.com/Josephdara/gke-platform/pull/20), merged 2026-10-06 23:00:27 | Chart 1.0.0 and the staging Gateway. Head of `main` at the first bootstrap |
| `d6a167dba72f71f2b075b054e0582adf64561e6d` | [#22](https://github.com/Josephdara/gke-platform/pull/22), merged 03:27:54 | Skip the dry run for the policies; fixed the first bootstrap. Head at the second |
| `3e04148e922316ec542823ba50bf3df2b4e42ea0` | [#21](https://github.com/Josephdara/gke-platform/pull/21), merged 03:59:36 | Policies switched to Deny, merged during the session |

The API ran release C, `sha-4f848fc` (`sha256:5eefe9ae99fadc5b0837e468a38acd83bcd386a586b3da85d8a1f011caf60aa3`), unchanged since 2026-10-06. Before the session, all 7 controller images were copied into `staging-mirror` with `crane copy`; every copy reported the same digest as its source.

## Bootstrap

The first bootstrap, 03:04:00 to 03:19:50, timed out. The root Application stayed `OutOfSync/Missing` because its sync was rejected before any wave ran:

```text
one or more synchronization tasks are not valid: failed to discover server resources for group version policies.kyverno.io/v1: the server could not find the requested resource (retried 5 times).
```

Argo CD validates every resource in an Application before applying the first wave. The ValidatingPolicy API only exists once the `kyverno` Application, a wave earlier in the same sync, has installed its CRDs, so validation failed and nothing synced. The fix, [#22](https://github.com/Josephdara/gke-platform/pull/22), added `argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true` to the 7 policies.

The second bootstrap ran from 03:28:15 to 03:37:38 (9 min 23 s) and ended with `PASS  running image matches Git` at revision `d6a167d`. The root moved through `OutOfSync/Progressing` while the waves ran, then both Applications briefly reported `Synced/Degraded` before settling at `Synced/Healthy`. All three Applications, `kyverno`, `staging-platform`, and `staging-platform-verification-api`, were `Synced/Healthy`.

## Kyverno

The four Kyverno controllers were Running and all 7 ValidatingPolicies reported `READY true`. The workload webhook Kyverno generated from the policies was:

| Webhook | Failure policy | Namespace selector |
| --- | --- | --- |
| `vpol.validate.kyverno.svc-fail` | `Fail` | `kubernetes.io/metadata.name` in `staging`, and not in `kube-system` or `kyverno` |

Kyverno's other webhooks validate its own resources, such as policies and exceptions, not workloads.

## Audit, then Deny

With the policies in Audit, the policy reports for the API's Deployment and both Pods showed 7 passed and 0 failed each. A server dry run of the 8 fixtures in `platform/tests/policies/deployments.yaml` admitted all of them, as Audit should; Pod Security only warned on `bad-pod-security`, because it enforces on Pods, not Deployments.

[#21](https://github.com/Josephdara/gke-platform/pull/21), which switched the policies to Deny, was merged at 03:59:36, and all 7 policies reported Deny by 04:01:20. The same dry run then accepted the compliant Deployment and denied each `bad-*` copy with its policy's message:

| Fixture | Message |
| --- | --- |
| `bad-registry` | Every container image must come from us-east4-docker.pkg.dev/gke-build-proj/gke-build-proj-staging-images/. Publish the image through the pipeline and use that repository. |
| `bad-digest` | Every container image must be pinned by digest (image@sha256:<64 hex characters>). Use the digest the pipeline recorded, not a tag. |
| `bad-resources` | Every container must set resources.requests.cpu, resources.requests.memory, resources.limits.cpu, and resources.limits.memory. |
| `bad-labels` | metadata.labels must include project, environment, service, and owner. Add the missing labels. |
| `bad-service-account` | spec.serviceAccountName must be <environment>-<service>, built from the environment and service labels. Use the service's own Kubernetes service account. |
| `bad-pod-security` | securityContext.allowPrivilegeEscalation must be false on every container. |
| `bad-read-only-root` | securityContext.readOnlyRootFilesystem must be true on every container. Write temporary files to an emptyDir volume. |

`kubectl create deployment` with `docker.io/library/nginx:latest` was denied in `staging` with all 7 messages in one response, and admitted in `default`. After the switch, all three Applications stayed `Synced/Healthy`, the API's Pods kept 0 restarts, and HTTPS still returned 200.

## Network and external access

| Check | Result |
| --- | --- |
| DNS from an API Pod | `secretmanager.googleapis.com` resolved to `142.250.31.95` |
| Outbound connection from an API Pod | `egress blocked TimeoutError` |
| Gateway | Programmed by 03:51:39 at `8.228.232.35`, the same address the A record returned |
| HTTPS | 03:52:39: `{"service":"platform-verification-api","version":"sha-4f848fc","secretLabel":"v3"}`, HTTP 200 |
| Certificate | Subject `CN=api.staging.gke.josephdara.com`, issuer Google Trust Services `WR3`, valid from 2026-10-06 20:35:12 to 2027-01-04 21:31:07 |
| Pod in another namespace to the API's Service | `TimeoutError`, while its control connection to `www.google.com:443` succeeded |

## HPA, PDB, and capacity

The HPA reported CPU at 4% of its 70% target with 2 replicas, between its bounds of 2 and 3. The PDB required 1 Pod available and allowed 1 disruption. With Kyverno installed, the cluster stayed at 2 nodes: CPU requests were 1260m (65%) and 1404m (72%), and memory requests 34% and 42%.

## Teardown

Automated sync was turned off on the root Application and then the service Application, and the HTTPRoute and Gateway were deleted at 04:05:56. Forwarding rules, target HTTPS proxies, and URL maps were gone by 04:06:29, but three backend services and three health checks, for the service and the Gateway's default 404 and 500 backends, remained until a second check at 04:09:20 found them gone. No LoadBalancer Services or Gateways remained. A saved `lab_enabled=false` plan destroyed 8 resources, including the static IP and the A record; the node pool took 4 min 22 s and the cluster 5 min 32 s. The inventory of 13 resource types was empty, and a final plan reported `No changes` with exit code 0.

Creating the lab took 9 min 23 s of Terraform time, and it was removed within about an hour and a half.

## Deviations and gaps

| Item | What happened | Effect |
| --- | --- | --- |
| First bootstrap | Failed on the missing ValidatingPolicy API, as described above | Fixed in [#22](https://github.com/Josephdara/gke-platform/pull/22); about 25 minutes lost |
| Transient `Degraded` | Both Applications reported `Synced/Degraded` once during the second bootstrap | Recovered without action; the cause was not captured |
| Merging [#21](https://github.com/Josephdara/gke-platform/pull/21) | The first merge was refused because the required check for the updated branch had not finished | Merged 4 minutes later; branch protection worked as intended |
| Teardown wait | The documented loop waited only for forwarding rules, so it ended while backend services and health checks still existed | They were gone 3 minutes later; the loop now waits for all five types |
| Gateway timing | The wait loop started after other checks, so only an upper bound for programming was recorded | Programmed by 03:51:39 |
| Audit duration | The Audit phase lasted about 22 minutes, over one service's workloads | Enough here; a multi-team platform would audit for days |
| Release C evidence | The evidence bucket listing was not captured | Not captured on 2026-10-06 either; see [Identity, secrets, and isolation](2026-10-06-isolation.md#deviations-and-gaps) |
| Upstream rate limit | Before the session, copying Redis from `public.ecr.aws` hit `TOOMANYREQUESTS` three times before succeeding | The kind of failure the mirror keeps out of bootstraps |

## Follow-ups

- Run `platform/tests/live-checks.sh` at the start of the next session; it repeats this session's non-disruptive checks.
- Acceptance tests: load with HPA scaling, Pod failure, node drain, and alert delivery.
