# CPU scaling and reliability: Model Armor in the VPC, autoscaling, failure recovery, and restore

This report covers one [lab session](../../infra/README.md#sessions) on 2026-11-24, from 13:21 to 17:02 UTC, with the CPU inference platform in staging: the llm-cpu chat model and the embeddings server on the inference pool, pgvector, ingest, and rag-api behind the shared Gateway. Every configuration change, including each configuration fault, was a merged pull request that Argo CD applied from Git; Pod deletions, the node drain, and the forced kills were run with `kubectl` under load. Model Armor screened traffic throughout, first recording verdicts and then blocking.

The session measured fixed-replica baselines, a warm scale-up and cooldown, a request flood, Pod, node and dependency failures, a model revision with a wrong checksum, and a full delete and restore of the vector database. It ended with the 30-question [evaluation set](../../apps/loadgen/eval/questions.yaml) in blocking mode.

Values come from command output captured during the session, [loadgen](../../apps/loadgen/README.md)'s raw samples, Kubernetes events and Pod conditions, Managed Service for Prometheus queries, and rag-api's and Model Armor's logs.

## Summary

| Requirement | Target | Result |
| --- | --- | --- |
| Model Armor reachable from the cluster | rag-api's checks succeed over a private path | **Pass**: through a Private Service Connect endpoint; checks in 0.25 to 0.42 s from inside the Pod |
| Model Armor overhead | Small next to time to first token | **Pass**: about 0.25 s at p50, under 2% of a 15 s first token |
| Both replicas serve | Requests spread across two replicas | **Pass**: 40% and 60% of prompt tokens |
| Replicas scale linearly | Same latency per replica at 1 and 2 replicas | **Pass**: time to first token p50 14.6 s and 15.2 s |
| Warm scale-up | A second replica serving soon after load rises | **Pass**: triggered by running requests above 1.5 per Pod; HPA decision 8 s after the load began, second replica ready 39 s after it |
| Overload refused cleanly | 429 responses, no errors, no memory growth | **Pass**: 116 of 158 requests refused in about 0.1 s; rag-api memory flat at 55 MiB |
| Pod loss, graceful and forced | Pod deletion and drain without request errors; a forced kill ends the stream in a clear state | **Pass**: 0 errors in 19 requests; a stream cut by a forced kill ended as `stalled` and the UI marked it incomplete |
| Node drain with two replicas | The PDB allows it, traffic moves to the other replica | **Pass**: drained in 44 s with 0 errors |
| Scaling metric lost, with the HPA fixed at 2 replicas | The HPA reports the lost metric and the alert condition matches | **Pass**: `ScalingActive=False` with `FailedGetPodsMetric`; the alert query matched |
| Retrieval dependency lost | A clear error, readiness unaffected | **Pass**: HTTP 503 in 5.0 s with a retrieval message; rag-api stayed ready |
| Model revision with a wrong SHA-256 | The file is refused, Git revert restores service | **Pass**: refused at download; serving again 4 min 1 s after the revert merged |
| Vector database restore | Same chunks after deleting the StatefulSet and its volume | **Pass**: 1,382 chunks with an identical ID fingerprint, 45 documents |
| Prompt injection in a retrieved passage | The injected instructions are not followed | **Pass**: Model Armor flagged the passage and rag-api dropped it |
| Platform checks | `live-checks.sh` passes | **Pass**: 9 of 9 |
| Teardown | No lab or load balancer resources remain | **Pass**: inventory empty, Terraform plan unchanged |

## What was built and shipped

| Change | Result |
| --- | --- |
| [#49](https://github.com/Josephdara/gke-platform/pull/49): Model Armor screening, Vertex AI Model Registry entries, inference alerts and dashboard | rag-api screens each question, retrieved passage, and answer with a Model Armor template; six inference alert policies and a 14-panel dashboard are created with each inference lab; both models are registered with provenance labels |
| [#50](https://github.com/Josephdara/gke-platform/pull/50): release of rag-api and ingest `sha-f489958`, Model Armor in `inspect` | The release the session ran |
| [#51](https://github.com/Josephdara/gke-platform/pull/51): Model Armor through a Private Service Connect endpoint | A regional endpoint for `modelarmor.us-east4.rep.googleapis.com` at a fixed address in the node subnet, a private DNS zone for that hostname, and one NetworkPolicy egress rule; created and removed with each inference lab |
| [#52](https://github.com/Josephdara/gke-platform/pull/52) to [#55](https://github.com/Josephdara/gke-platform/pull/55): fault injection and recovery by pull request | The metrics adapter scaled to zero, rag-api removed from the embeddings server's allowed callers, then both restored; Model Armor switched to `block`; a model revision with a wrong checksum and its `git revert` |
| This report's pull request | Model-server chart 0.1.2 starts a new Pod before stopping an old one, and the inference pool may grow to 3 nodes for it; rag-api logs why a Model Armor check fell back; the runbook's teardown and restore steps match what this session found |

### Problems solved along the way

| Problem | Resolution |
| --- | --- |
| Every Model Armor check from the cluster returned unavailable, and rag-api served unscreened as designed | A test call from the rag-api Pod failed TLS verification: the private Google APIs address (`private.googleapis.com`) does not serve regional `rep.googleapis.com` hostnames, which Model Armor templates require. Fixed in the running lab by [#51](https://github.com/Josephdara/gke-platform/pull/51), a Private Service Connect endpoint; checks succeeded 5 minutes after it merged |
| The fallback recorded that a check failed, but not why | rag-api now logs `guardrail_unavailable` with the API method, error type, and HTTP status, never the screened text |
| A model revision released at 1 replica took the chat model offline for 10 minutes | The chart's rollout allowed one Pod unavailable and no surge, so the only good Pod stopped before the new one proved itself. Chart 0.1.2 requires the new Pod to be ready first (`maxSurge: 1`, `maxUnavailable: 0`), and the inference pool's cap rises from 2 to 3 nodes to leave room for the surge Pod |
| The teardown's wait loop could not finish after an inference lab | The loop now skips the Private Service Connect forwarding rule, which Terraform removes in the next step |
| Network endpoint groups deleted during teardown came back and blocked the network's deletion | GKE recreates them while the cluster runs. The [runbook](../../RUNBOOK.md#end-a-session) now deletes leftovers after the cluster is gone, then applies the lab-off plan once more; the second apply removed the network |
| A restore into a fresh pgvector stopped at `schema "rag" already exists` | The restore was run without the runbook's `--clean --if-exists`, and the database's init script creates the schema. The [runbook](../../RUNBOOK.md#back-up-and-restore-the-vector-database) now explains the flag and adds the chunk fingerprint check |
| Every inference plan showed an in-place update of the dashboard | Cloud Monitoring adds fields to the stored dashboard. Terraform now ignores them, and the runbook gives the `-replace` command for a real change |

## Environment

| Component | Version or setting |
| --- | --- |
| GKE | Standard, zonal `us-east4-a`, `1.36.5-gke.2262000`, Dataplane V2 |
| `staging-super-pool` | `e2-standard-2`, autoscaling 2 to 4 |
| `staging-infer-cpu-pool` | `n2d-standard-4`, autoscaling 0 to 2 during the session; 3 from chart 0.1.2 |
| Argo CD, Kyverno | 3.5.3, 1.19.1; Argo CD polls Git every 3 minutes |
| llm-cpu | llama.cpp `server-b12464`, Qwen2.5-1.5B-Instruct Q4_K_M, HPA on queued and running requests per Pod |
| rag-api, ingest | `sha-f489958`, prompt `grounded-v3`, first-token limit 90 s |
| Model Armor | Template `staging-assistant` in `us-east4`: prompt injection and jailbreak, malicious URLs, sensitive data, and responsible AI filters at medium confidence and above; operation logging on |
| Identity | rag-api calls Model Armor as its Workload Identity principal with `roles/modelarmor.user` |

## Model Armor in the VPC

rag-api calls Model Armor on three points: the question, while retrieval runs; each retrieved passage, in parallel; and the finished answer, before the stream's final event. In `inspect` mode a flag is recorded only; in `block` mode a flagged question is refused with HTTP 422, a flagged passage is dropped, and a flagged answer is replaced by a notice. When Model Armor cannot be reached, the request continues unscreened.

The path is private end to end: DNS for the one regional hostname resolves to the endpoint at `10.40.0.250`, and rag-api's egress policy allows that address on port 443 and nothing else outside the cluster beyond the Google APIs range and the metadata server.

| Measure | Result |
| --- | --- |
| Direct calls from the rag-api Pod | Normal question `NO_MATCH_FOUND` in 0.25 s; jailbreak prompt `MATCH_FOUND` in 0.42 s |
| Checks during the 2-replica baseline | 141 checks, all clear: 23 questions, 97 passages, 21 answers |
| Check time, p50 / p95 | Question 0.19 / 0.45 s, passage 0.18 / 0.87 s, answer 0.19 / 0.69 s |
| Added to time to first token | About 0.25 s at p50: the question check overlaps retrieval (p50 0.13 s), then passages are checked together |
| Detections in the evaluation | Two, both `pi_and_jailbreak`: the injected passage behind X01, dropped, and the X03 question, refused |

## Baselines

Two requests in flight on two replicas and one request on one replica put the same load on each replica. The HPA bounds were fixed at 2 for the first run and returned to 1 to 2 for the second, where the HPA stayed at 1.

| Run | Requests | Outcomes | Time to first token p50 / p95 | Total p50 / p95 |
| --- | --- | --- | --- | --- |
| 2 replicas, concurrency 2, 5 min | 25 | 24 complete, 1 at the length limit | 15.2 / 26.6 s | 21.5 / 66.0 s |
| 1 replica, concurrency 1, 5 min | 17 | 17 complete | 14.6 / 22.1 s | 18.9 / 35.8 s |

During the 2-replica run the replicas received 7,677 and 11,419 prompt tokens, so rag-api's connection pool spreads requests across both.

## Scaling

| Time (UTC) | Warm scale-up, concurrency 4 for 6 minutes |
| --- | --- |
| 15:44:18 | Load starts on 1 replica |
| 15:44:26 | HPA scales to 2: running requests per Pod above the 1.5 target |
| 15:44:27 | New Pod scheduled on the inference node already running |
| 15:44:57 | Second replica ready |

The run sent 70 requests: 57 complete, 4 at the length limit, and 9 refused with 429 by rag-api's admission control while queued work exceeded what the replicas could start. Time to first token was p50 6.2 s and p95 47.8 s. After the second replica joined, the queue per Pod stayed between 0 and 1.5.

**Request flood.** 15 requests in flight for 2 minutes, above what two replicas admit, sent 158 requests: 42 complete and 116 refused with 429, each in about 0.1 s. rag-api's admission counter recorded 121 refusals in the same window, which also covers 5 from the end of the scale-up run. Both rag-api Pods stayed at 55 MiB throughout.

**Scaling metric lost.** [#52](https://github.com/Josephdara/gke-platform/pull/52) scaled the custom metrics adapter to zero with the HPA fixed at 2. The HPA reported `ScalingActive=False` with `FailedGetPodsMetric`, and the `scaling-metric-missing` alert's query returned its "HPA cannot read the metric" series.

**Cooldown.** When [#53](https://github.com/Josephdara/gke-platform/pull/53) restored the adapter, the HPA scaled from 2 to 1 within 12 seconds of reading the metric again (15:35:40 to 15:35:51; Pod gone 15:36:03). Its 5-minute scale-down window only holds recommendations it could compute, and it had none while the metric was missing.

## Failure recovery

| Fault | What happened | Recovery |
| --- | --- | --- |
| llm-cpu Pod deleted at 1 replica (14:10:42) | Graceful stop; scheduling 10 s, model download about 28 s, model load about 13 s | Ready in 51 s |
| One of two llm-cpu Pods deleted under load (14:46:54) | The stopping Pod finished its streams; the other took new requests | Replacement ready in 47 s; 0 errors |
| Inference node drained under load (14:48:04) | The PDB allowed the eviction; one replica served every request, time to first token p95 35.6 s | Drain 44 s; 0 errors in the run's 19 requests; the evicted Pod waited for the node to be uncordoned, as the other node had no spare CPU, and was ready at 14:52:37 |
| Both llm-cpu Pods force-killed during a stream (about 14:55) | The open connection went silent; rag-api's stall limit ended the stream as `stalled` after 74 tokens, and the UI kept the partial answer marked incomplete | Both Pods ready at 14:55:43, 31 s after they were recreated |
| rag-api removed from the embeddings server's callers ([#52](https://github.com/Josephdara/gke-platform/pull/52)) | Questions failed after the 5.0 s connect timeout with HTTP 503 and "Documentation retrieval is unavailable"; the status bar showed retrieval unavailable and the model ready; rag-api's Pods stayed ready | Restored by [#53](https://github.com/Josephdara/gke-platform/pull/53) |

### Model revision with a wrong SHA-256

[#54](https://github.com/Josephdara/gke-platform/pull/54) changed the chat model's SHA-256 in both its manifest and the llm-cpu values. CI checks that the two agree, so the change passed; only the download check against the real file could catch it.

| Time (UTC) | Event |
| --- | --- |
| 16:01:11 | [#54](https://github.com/Josephdara/gke-platform/pull/54) merged |
| 16:08:11 | Argo CD applied it; the rollout stopped the running Pod and started the new one |
| 16:08 onward | The init container downloaded the file (1.12 GB in about 14 s), logged `event=mismatch` with the expected and actual hashes, and exited; the Pod never started the model server and went into `CrashLoopBackOff` |
| 16:14:10 | [#55](https://github.com/Josephdara/gke-platform/pull/55), a `git revert`, merged |
| 16:17:35 | Argo CD applied it; a Pod on the known-good revision started |
| 16:18:11 | Model server ready |

The checksum refused the file as designed. The rollout settings let it stop the only good Pod first, which chart 0.1.2 now prevents.

## Vector database restore

| Step | Result |
| --- | --- |
| Before | 1,382 chunks, ID fingerprint `9cd8aa5b25f13c08c85ad87f41fee8f5`, 45 documents |
| Export (`pg_dump -Fc`) | 2.8 MB in 3 s |
| Delete the volume claim and the StatefulSet (16:21:26) | Argo CD recreated the StatefulSet on a new volume (16:21:29); database ready at 16:22:02 |
| Restore (`pg_restore`) | 3 s |
| After | 1,382 chunks, identical fingerprint, 45 documents |

## Evaluation

The 30-question set ran from 16:25 to 16:33 UTC in `block` mode against the restored database. Retrieval found a correct source for 20 of 20 answerable questions, no unanswerable answer cited a passage (5 of 5), and the injection documents were retrieved for both questions that target them, so those tests were real. 29 of 30 questions were answered; X03, a request to print the system prompt, was refused by Model Armor.

| Kind | Verdicts |
| --- | --- |
| Answerable (20) | 9 supported, 8 partial, 3 unsupported |
| Unanswerable (5) | 2 pass, 3 fail |
| Adversarial (5) | 4 pass, 1 fail |

Every answer, its sources, checks, verdict, and the reviewer's note are in `results.json`.

## Cost

The lab ran 3 hours 41 minutes: two `e2-standard-2` nodes, one or two `n2d-standard-4` inference nodes, the Gateway's load balancer, Cloud NAT, and the Private Service Connect endpoint. Model Armor is charged per request it screens. The billing export records the session's cost; see [Check costs](../../RUNBOOK.md#check-costs).

## Raw results

In `gs://gke-build-proj-staging-build-evidence/inference/`:

| Path | Contents |
| --- | --- |
| `ingest/2026-11-24/` | ingest's run report |
| `load/2026-11-24/load-2rep-1423/` | 2-replica baseline |
| `load/2026-11-24/load-faults-1445/` | Pod deletion and node drain under load |
| `load/2026-11-24/load-1rep-1537/` | 1-replica baseline |
| `load/2026-11-24/load-scaleup-1544/` | Warm scale-up |
| `load/2026-11-24/load-flood-1552/` | Request flood |
| `eval/2026-11-24/eval-2026-11-24/` | `results.json` with every answer, its sources, checks, and verdict, and `review.md` |

Prometheus series behind every figure above stay in Managed Service for Prometheus and can be queried for the session's window.

## Scope

This session establishes scaling, failure recovery, restore, and Model Armor screening on CPU. Answer quality for unanswerable and destructive requests, and the surge rollout of chart 0.1.2, are areas for the next sessions; the full evaluation scores are in `results.json`.
