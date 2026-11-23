# Inference foundation: model servers, admission, identity, and the scaling metric

This report records the first [lab session](../../infra/README.md#sessions) with the inference workload class: the `staging-inference` namespace, the CPU inference pool scaling from zero, the model-server chart running llama.cpp (`llm-cpu`) and Text Embeddings Inference (`embeddings`), the two inference admission policies, Workload Identity access to the models bucket, and the custom metric behind the llm-cpu HPA. Values come from command output captured during the session, mostly from [`inference-checks.sh`](../tests/inference-checks.sh) and [`live-checks.sh`](../tests/live-checks.sh). Three problems found on the first attempt were diagnosed and fixed during the session; see [Problems solved](#problems-solved).

## Summary

| Requirement | Target | Result |
| --- | --- | --- |
| Lab with the inference pool | 15 lab resources added, nothing destroyed; the inference pool accepted with 0 nodes | **Pass** |
| Model servers scheduled and running from Git | Both Pods Running, digests equal to `values-staging.yaml` at the synced commit | **Pass** after [#35](https://github.com/Josephdara/gke-platform/pull/35) set ephemeral-storage defaults; see [Problem 1](#1-model-servers-unschedulable) |
| Running images match Git | Every running digest equals `values-staging.yaml` | **Pass**: confirmed by `live-checks.sh` and `inference-checks.sh`; see [Problem 2](#2-bootstrap-timed-out) |
| Inference pool scales from zero | The pending llm-cpu Pod creates the first node | **Pass**: scale-up triggered 2 s after the Pod was created, node created at +33 s |
| Model download is verified | Every file's size and SHA-256 checked before the server starts | **Pass**: 1.1 GB downloaded in 13.8 s and checked in 6.8 s |
| Cold start within the startup limit | llm-cpu Ready within 600 s | **Pass**: Ready 104 s after the Pod was created, 0 restarts |
| Admission denies broken model servers | Each broken fixture denied by the policies its test expects | **Pass**, 3 of 3 |
| Allowed caller is served | A `debug` Pod in `staging` gets a chat completion and tokens | **Pass** |
| Callers are limited per server | The `debug` caller cannot reach embeddings | **Pass** |
| Unlisted namespaces are refused | A Pod in another namespace cannot reach llm-cpu, while its internet access works | **Pass** |
| Workload Identity grants only what is listed | llm-cpu's identity reads the models bucket and is refused a secret | **Pass**: size matched the manifest; HTTP 403 for the secret |
| Scaling metric reaches the HPA | `llamacpp:requests_deferred` in the custom metrics API; HPA `ScalingActive=True` | **Pass** |
| Existing platform unaffected | `live-checks.sh` passes | **Pass**, 9 of 9 |
| Teardown | No lab or load balancer resources remain; persistent resources untouched | **Pass** after removing a leftover network endpoint group; see [Problem 3](#3-teardown-blocked-on-the-network) |

## Environment

| Component | Version or setting |
| --- | --- |
| GKE | Standard, zonal `us-east4-a`, Regular channel; control plane and nodes `1.36.5-gke.1982000` |
| `staging-super-pool` | 2 × `e2-standard-2` (autoscaling 2 to 4); allocatable per node 1,930m CPU, 5.9 GiB memory, 8.4 GB ephemeral storage |
| `staging-infer-cpu-pool` | 0 to 2 × `n2d-standard-4`, taint and label `workload-class=llm-cpu`; allocatable 3,920m CPU, 13.0 GiB memory, 18.8 GB ephemeral storage |
| Argo CD | 3.5.3 from `staging-mirror` |
| Kyverno | 1.19.1 from `staging-mirror`, 9 ValidatingPolicies |
| Custom metrics adapter | `custom-metrics-stackdriver-adapter` `v0.16.12-gke.4` (`sha256:6773160c63486991f0332b7d3beb0eb45d767755b617592cb22866d09d34bd9d`) |
| llm-cpu | llama.cpp `server-b12464` (`sha256:5b43086e3ba7ea5794d72904654f6cd41224a9b1c6ac0398f4940ee380d30f23`); Qwen2.5-1.5B-Instruct Q4_K_M at revision `91cad51170dc346986eccefdc2dd33a9da36ead9`; 3 CPU, 3Gi; 2 slots of 4,096 tokens |
| embeddings | Text Embeddings Inference `cpu-1.9.4` (`sha256:2538ea1c9640d3763b15af668039d24172d063b42337b0c27796fc2be180c78d`); bge-small-en-v1.5 at revision `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` |
| Model download | distroless `python3-debian13:nonroot` (`sha256:6c4cb3bfa4b555429dd19541796a6ba6b30c84675b460bd0bd5072f7d5bdae71`) |

## Revisions

| Commit | Pull request | Change |
| --- | --- | --- |
| `34da70fe64cc0e87165ca70a0542e107b19b80cf` | [#32](https://github.com/Josephdara/gke-platform/pull/32) | Inference namespace, CPU pool, models bucket, image mirror |
| `ae177a007c8059f8bf7afc628ba12ec58ae2effe` | [#33](https://github.com/Josephdara/gke-platform/pull/33) | Model-server chart 0.1.0, inference policies, metrics adapter |
| `70c671e983bfcf6d46dc4df9023ed587a4ce29b3` | [#34](https://github.com/Josephdara/gke-platform/pull/34) | `inference-checks.sh`. Head of `main` at the bootstrap |
| `ff5cd6526132e4991a87bfdb0d6dd4e1c210b81c` | [#35](https://github.com/Josephdara/gke-platform/pull/35) | LimitRange ephemeral-storage defaults, merged during the session. Head for every check |

The API ran `sha-d1b3f48` (`sha256:daba5ff446f0051d31c31e6ae29fcbcc8e5d70ae81b74e312a9612656378b7b0`).

## Lab and bootstrap

The saved lab-on plan, with `lab_enabled=true`, `inference_cpu_enabled=true`, and `inference_min_nodes=0`, added 15 resources and destroyed none: the usual 11 lab resources, `staging-infer-cpu-pool`, and the private `staging-googleapis` zone with its two records. The apply ran from 20:32:02 to about 20:43:40 UTC, 11 min 38 s. GKE created the inference pool with 0 nodes in 17 seconds.

The bootstrap started at 21:06:15. Argo CD accepted the metrics adapter's upstream manifest and reported `custom-metrics-adapter` `Synced/Healthy`. The API reached `Synced/Healthy`, and the bootstrap then timed out as described in [Problem 2](#2-bootstrap-timed-out).

## Cold start

Both Pods were recreated at 21:31:19 UTC. Offsets are from that time.

| Stage | llm-cpu | embeddings |
| --- | --- | --- |
| Node | New node created at +33 s, Ready at +44 s | Existing super-pool node |
| Scheduled | +44 s | +0 s |
| Image pulls | download image 9.6 s, llama.cpp 8.9 s | download image 4.8 s, TEI 14.6 s |
| Model download | 13.8 s (1,117,320,736 bytes) | 4.5 s (7 files) |
| Checksums | 6.8 s | 1.3 s |
| Init container finished | +82 s | +13 s |
| Server started | +91 s | +29 s |
| Model loaded | +98 s | +37 s |
| **Ready** | **+104 s** | **+40 s** |
| Restarts | 0 | 0 |

The init container got its token from the metadata server with no Kubernetes service account token mounted, through the egress rule to `169.254.169.254` on ports 80 and 8080. The download reached Cloud Storage through the private `googleapis.com` zone.

## Admission

Server-side dry runs in `staging-inference` of the policy fixtures from [`policies/deployments.yaml`](../tests/policies/deployments.yaml):

| Fixture | Denied by |
| --- | --- |
| `llm-cpu-no-provenance` | `require-model-provenance` |
| `llm-cpu-no-bounds` | `require-inference-bounds` |
| `inference-breaks-all` | `require-approved-registry`, `require-image-digest`, `require-resources`, `require-labels`, `require-service-account`, `restrict-pod-security`, `require-read-only-root-filesystem` |

The running llm-cpu and embeddings Deployments were admitted, and their running digests matched `values-staging.yaml` at `ff5cd65`.

## Inference path and service time

A `debug` Pod in `staging`, using the API image and a temporary `staging-debug` service account, called llm-cpu through its Service. A chat completion answered `'One planet is Earth.'` in 6 tokens, and `/tokenize` returned 6 tokens.

The service time was measured with three sequential requests at the size rag-api will send: a prompt of about 2,000 tokens of text, 2,061 with the chat template, and 384 output tokens forced with `ignore_eos`. Prompt caching was off, and each prompt started with a unique line, so no request reused another's prompt processing.

| Run | Total | Prompt processing | Generation |
| --- | --- | --- | --- |
| 1 | 56.6 s | 2,061 tokens in 35.7 s | 384 tokens in 20.8 s |
| 2 | 57.2 s | 2,061 tokens in 35.8 s | 384 tokens in 21.4 s |
| 3 | 57.3 s | 2,061 tokens in 36.2 s | 384 tokens in 21.0 s |

The median service time S is 57.2 s. With 2 slots and rag-api's 120-second deadline, the admission cap per replica is 2 × (120 − 57.2) / 57.2 = **2 queued requests**, on top of the 2 in progress. Prompt processing at about 57 tokens per second, not generation, dominates a full-size request on CPU.

## Isolation and identity

| Check | Result |
| --- | --- |
| `debug` in `staging` to embeddings | `TimeoutError`. Both sides refuse it: the `debug` egress rule allows only llm-cpu, and embeddings lists only rag-api and ingest as callers |
| Pod in a temporary namespace to llm-cpu | `TimeoutError`, while the same Pod connected to `www.google.com:443` |
| Identity reported by the metadata server to a Pod running as `staging-llm-cpu` | `gke-build-proj.svc.id.goog` |
| Models bucket read as `staging-llm-cpu` | Object metadata returned, size `1117320736`, equal to the model manifest |
| Secret read as `staging-llm-cpu` | HTTP 403. The network path to Secret Manager was open for this Pod, so IAM refused it |

## Scaling metric

The custom metrics API returned `prometheus.googleapis.com|llamacpp:requests_deferred|gauge` for the llm-cpu Pod. The HPA reported `AbleToScale=True ScaleDownStabilized`, `ScalingActive=True ValidMetricFound`, and `ScalingLimited=False DesiredWithinRange`. Before llm-cpu was running, the HPA reported `ScalingActive=False` because the metric did not exist yet, which is expected. Scaling up under load was not tested.

## Manual requests

Three requests were sent through `kubectl port-forward` as a cluster administrator. Port-forwarding goes through the API server and kubelet, so the NetworkPolicies do not apply to it; the `staging-inference` developer Role does not grant `pods/portforward`.

| Request | Result |
| --- | --- |
| Chat: explain a LimitRange in three sentences | 33 prompt and 71 completion tokens. The answer described only the maximum and missed that a LimitRange works per container and fills in defaults, the behaviour behind [Problem 1](#1-model-servers-unschedulable) |
| Streaming chat: a haiku about autoscaling | One server-sent event per token, ending with `[DONE]`. 13 new prompt tokens in 0.30 s, 24 reused from the prompt cache; 22 tokens generated at 25.5 tokens per second |
| Embedding of one sentence | 384 dimensions, as bge-small-en-v1.5 defines |

## Capacity

| Node | CPU requests | Memory requests | Ephemeral-storage requests |
| --- | --- | --- | --- |
| Inference node | 3,634m of 3,920m (92%) | 32% | 2Gi of 18.8 GB |
| Super-pool node 1 | 1,871m of 1,930m (96%) | 53% | 512Mi |
| Super-pool node 2 | 1,674m of 1,930m (86%) | 47% | 0 |

On the inference node, llm-cpu's 3 CPU and system Pods leave about 290m of CPU, while memory is two-thirds free. The super pool is nearly full on CPU with the platform, the API, and embeddings.

## Regression

`live-checks.sh` passed 9 of 9 at 21:40 UTC. Inside the VPC, `secretmanager.googleapis.com` resolved to `199.36.153.10` through the private zone, and the API still refused outbound connections and served its mounted secret's label, `v3`. Admission in `staging` still denied a naive Deployment with all 7 base policies. HTTPS through the Gateway answered 200.

## Teardown

Automated sync was turned off on `staging-platform` and the API's Application, and the HTTPRoute and Gateway were deleted. The load balancer was gone at 21:52:56 UTC. The lab-off plan destroyed the same 15 resources; the apply started at 21:54:42 and stopped at the network, as described in [Problem 3](#3-teardown-blocked-on-the-network). After the NEG was deleted, a new plan destroyed the network.

At 22:08 UTC the project had no clusters, instances, disks, addresses, forwarding rules, proxies, URL maps, backend services, health checks, NEGs, routers, networks, or firewall rules, and only the public `staging-dns` zone. A lab-off plan reported no changes with exit code 0. The lab ran for about 1 hour 35 minutes.

## Problems solved

### 1. Model servers unschedulable

**What happened.** After the bootstrap applied the Applications, both model-server Pods stayed `Pending`, and the cluster autoscaler did not add an inference node.

**How it showed.** At 21:11 UTC, `staging-llm-cpu` and `staging-profile` were `Synced/Degraded` and `staging-embeddings` was `Synced/Progressing`. The scheduler and autoscaler events:

```text
0/2 nodes are available: 1 Insufficient cpu, 2 Insufficient ephemeral-storage.
Pod didn't trigger scale-up: 1 node(s) had untolerated taint(s), 1 Insufficient ephemeral-storage
```

**Root cause.** The `staging-inference` LimitRange set a per-container ephemeral-storage maximum of 40Gi and no default. When a LimitRange has a maximum but no default, Kubernetes uses the maximum as the default limit, and the default limit as the default request. The chart's init container sets CPU and memory but no ephemeral storage, so the API server gave it a 40Gi request and limit:

```text
init fetch-model: {"limits":{"cpu":"500m","ephemeral-storage":"40Gi","memory":"256Mi"},"requests":{"cpu":"200m","ephemeral-storage":"40Gi","memory":"128Mi"}}
```

A Pod's effective request is the larger of its largest init container and the sum of its app containers, so each Pod asked for 40Gi. A super-pool node allocates 8.4 GB of ephemeral storage and an inference node 18.8 GB. The local checks did not catch it: chart renders and the Kyverno CLI never apply LimitRanges, only the API server does.

**How it was found.** Comparing the Pods' admitted requests with the nodes' allocatable resources.

**Fix and time lost.** [#35](https://github.com/Josephdara/gke-platform/pull/35) added explicit ephemeral-storage defaults to the LimitRange: 128Mi requested, 1Gi limit. Argo CD synced it at 21:29:46 UTC, and deleting the two Pending Pods at 21:31:18 recreated them with the new defaults. About 20 minutes lost.

**What stops it recurring.** Model-server chart 0.1.1 sets the init container's ephemeral-storage request and limit itself, to the values that ran here, so it no longer depends on namespace defaults. The LimitRange maximum is now 16Gi, below what an inference node can allocate, so the cap means something.

### 2. Bootstrap timed out

**What happened.** `bootstrap.sh` waited its full 600 seconds and exited with `Timed out`.

**Root cause.** A consequence of problem 1: `staging-platform` stayed `Synced/Progressing` while the embeddings Application it contains waited on the Pending Pod. The API itself was `Synced/Healthy`.

**Effect.** The bootstrap's closing report of versions and running digests was not printed. `live-checks.sh` covered the same image check later, and `inference-checks.sh` checked the model servers' digests. The bootstrap was not rerun.

### 3. Teardown blocked on the network

**What happened.** The lab-off apply destroyed 14 of 15 resources, then failed on the network:

```text
Error: Error waiting for Deleting Network: The network resource 'projects/gke-build-proj/global/networks/staging-vpc' is already being used by 'projects/gke-build-proj/zones/us-east4-a/networkEndpointGroups/k8s1-6b050ef5-staging-staging-platform-verification--8-577022ff'
```

**Root cause.** GKE creates a network endpoint group (NEG) for the Service behind the Gateway. Deleting the Gateway and HTTPRoute removed the load balancer, but the NEG belongs to the Service, which still existed. The cluster was deleted before the NEG controller removed it, leaving an empty NEG with nothing to clean it up. The documented wait loop checked forwarding rules, proxies, URL maps, backend services, and health checks, but not NEGs.

**Fix and time lost.** The NEG had 0 endpoints and was the only thing left on the network. It was deleted by name, a new lab-off plan showed 1 resource to destroy, and its apply removed the network. About 3 minutes lost.

**What stops it recurring.** The [runbook's](../../RUNBOOK.md#end-a-session) wait loop now also waits for network endpoint groups, with the command to delete one that remains.

### Smaller problems

| Problem | Effect |
| --- | --- |
| Listing the budget with `gcloud billing budgets list` failed: the Budget API is not enabled, and the budget was created in the console | The budget was checked in the console instead; the API stays off |
| `inference-checks.sh` printed `returned<pod name>` on its metric line | Cosmetic; the check's result was correct. Fixed |
| The documented check count for `inference-checks.sh` was 6; it runs 7 | Documentation fixed |

## Findings

- **A 1.5B model answers fluently but imprecisely without source material.** That is the reason for the retrieval step in front of the chat model.
- **Generation slows as the context grows:** 25.5 tokens per second with a short prompt, about 18 with 2,061 tokens.
- **The super pool is nearly full on CPU.** Adding rag-api, the vector database, and a load generator scales it toward its maximum of 4 nodes.
- **The inference node is CPU-bound, not memory-bound,** so llama.cpp's memory can grow but its CPU request cannot.

## Scope

The service time was measured one request at a time; the concurrent case and the second inference node are measured by the load and scaling runs that follow. The cold-start figures and checks were repeated with model-server chart 0.1.1; see [CPU serving](2026-11-22-cpu-serving.md#lab-and-bootstrap).
