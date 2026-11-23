# CPU serving: the assistant in staging, its release and rollback under load, and the first evaluation

This report covers two [lab sessions](../../infra/README.md#sessions) with the full assistant on the CPU inference pool: rag-api with its web interface, pgvector, ingest, the llm-cpu chat model, and the embeddings server, all deployed by Argo CD and served at `https://assistant.staging.gke.josephdara.com/`.

- **2026-11-20:** the first deployment. The corpus was loaded, the site was checked end to end, and the improvements found there were shipped before the second session.
- **2026-11-22:** a rag-api release, its rollback by Git revert, and a re-release, each timed from merge to healthy, with [loadgen](../../apps/loadgen/README.md) streaming answers through the load balancer during the release and the rollback; then the first scored run of the 30-question [evaluation set](../../eval/questions.yaml).

Values come from command output captured during the sessions, loadgen's raw samples, rag-api's logs, and the check scripts.

## Summary

| Requirement | Target | Result |
| --- | --- | --- |
| The assistant answers through the Gateway | A signed-in user gets streamed answers over HTTPS | **Pass** |
| Corpus loaded | Every document loaded, none failed | **Pass**: 45 of 45 documents, 1,382 chunks, in 9 min 32 s from an empty database |
| Release under streaming load | No stream cut, no request reaching a Pod after its preStop ends | **Pass**: 177 requests, 0 cut, 0 refused |
| Rollback by Git revert under streaming load | The same | **Pass**: 203 requests, 0 cut, 0 refused |
| Release and rollback time | Measured from merge to every new Pod ready | Release 3 min 54 s, rollback 3 min 52 s, re-release 6 min 39 s |
| First evaluation scored | Retrieval and answers scored separately, every result kept | **Pass** |
| Retrieval | 18 of 20 answerable questions retrieve a correct source in the top five | **Pass**: 20 of 20 |
| Unanswerable questions | No invented citations | **Pass**: 5 of 5 |
| Repeatable answers | The same question gets the same answer | **Pass**: 30 of 30 identical across runs |
| Platform unaffected | `live-checks.sh` and `inference-checks.sh` pass | **Pass**, 9 of 9 and 7 of 7 in both sessions |
| Teardown | No lab or load balancer resources remain | **Pass** in both sessions |

## What was built and shipped

| Change | Result |
| --- | --- |
| [#40](https://github.com/Josephdara/gke-platform/pull/40): rag-api and ingest deployed to staging | The assistant reachable over HTTPS through the shared Gateway, with its own backend and health-check policies, three Secret Manager secrets, and a suspended ingest CronJob started on demand |
| [#41](https://github.com/Josephdara/gke-platform/pull/41): ingest batches sized to the embeddings server | The embeddings server admits 8 inputs at a time and counts each input in a request. Batches of 4 load every document and leave 4 slots for rag-api's question embeddings while ingest runs |
| [#42](https://github.com/Josephdara/gke-platform/pull/42): the web interface and retrieval refined after the first deployment | Answers render as Markdown with copyable code blocks; sources are listed one row per document and link to the original page at the passage's section; at most two passages come from one document; messages no passage matches get a short answer labelled as general, using a relevance floor calibrated on sample questions, where off-topic messages scored at most 0.60 and documentation questions at least 0.69 |
| [#43](https://github.com/Josephdara/gke-platform/pull/43): loadgen and the evaluation set | A streaming client that records every request's outcome, timings, sources, and request ID, honours `Retry-After`, and scores retrieval automatically against 30 fixed questions |
| [#44](https://github.com/Josephdara/gke-platform/pull/44): prompt `grounded-v3` at temperature 0 | A simpler citation rule and greedy decoding, so answers stay close to the passages and repeat exactly |
| [#45](https://github.com/Josephdara/gke-platform/pull/45) to [#47](https://github.com/Josephdara/gke-platform/pull/47): release, rollback, re-release | Three rollouts driven only by Git, described below |

### Problems solved along the way

| Problem | Resolution |
| --- | --- |
| The first ingest run was refused by the embeddings server's concurrency limit | Diagnosed from the server's `no permits available` log and fixed by [#41](https://github.com/Josephdara/gke-platform/pull/41) in the same session; every later load had no failures |
| During the bootstrap, Applications can briefly reference their AppProject before it exists | Argo CD's retry resolves it within a few minutes; the [runbook](../../RUNBOOK.md#run-the-assistant) now describes it |
| GKE leaves the Gateway's network endpoint groups after the load balancer is removed | The [runbook's](../../RUNBOOK.md#end-a-session) teardown waits for them and deletes any that remain, so the network was never blocked |
| A local evaluation showed the model copying the prompt's example citation, and answers varying between runs | Found before the lab and fixed by [#44](https://github.com/Josephdara/gke-platform/pull/44) |
| Against a rate-limited account, loadgen's workers retried at once | Fixed before merging: a worker waits for the server's `Retry-After` |
| The runbook's lab resource counts predated the assistant's DNS record | Corrected to 12, or 16 with the inference pool |

## Environment

| Component | Version or setting |
| --- | --- |
| GKE | Standard, zonal `us-east4-a`; `1.36.5-gke.1982000` on 2026-11-20 and `1.36.5-gke.2262000` on 2026-11-22 |
| `staging-super-pool` | `e2-standard-2`, autoscaling 2 to 4 |
| `staging-infer-cpu-pool` | 0 to 2 × `n2d-standard-4`; one node in both sessions |
| Argo CD, Kyverno | 3.5.3, 1.19.1 |
| llm-cpu | llama.cpp `server-b12464` (`sha256:5b43086e3ba7ea5794d72904654f6cd41224a9b1c6ac0398f4940ee380d30f23`); Qwen2.5-1.5B-Instruct Q4_K_M at revision `91cad51170dc346986eccefdc2dd33a9da36ead9`; 3 threads; 2 slots of 4,096 tokens |
| embeddings | Text Embeddings Inference `cpu-1.9.4` (`sha256:2538ea1c9640d3763b15af668039d24172d063b42337b0c27796fc2be180c78d`); bge-small-en-v1.5; at most 8 concurrent inputs |
| pgvector | `sha256:b513c48566e4777cd3370451400000c78eda6a08131d68f4c31d4a76f27bd8fd`, one replica, 10 GiB disk |
| ingest | `sha256:6f0648006f67272016f0bd5e7c647f5cb340aee90cf6ce5b14da817a2c233491`; corpus `8937eb5aedca`, 45 Markdown documents |
| rag-api | 2 replicas; admission 3 per replica; 120-second deadline; preStop 10 s, termination grace 150 s |
| Load generator | loadgen through the Gateway; concurrency 2, cycling the 20 answerable questions, with an account exempt from the per-user rate limit |

## Revisions

| Commit | Pull request | Change |
| --- | --- | --- |
| `7de244faa38d97e4bf59d4d82ed6622313a04d7f` | [#40](https://github.com/Josephdara/gke-platform/pull/40) | rag-api and ingest deployed to staging. Head at the 2026-11-20 bootstrap |
| `0df923c82b04595870e320776ff32da01baae6a1` | [#41](https://github.com/Josephdara/gke-platform/pull/41) | ingest embedding batch of 4, merged during the 2026-11-20 session |
| `4b43bb549d1fbdff804fba16ad3e1f013251b32b` | [#42](https://github.com/Josephdara/gke-platform/pull/42) | Markdown answers, linked sources, relevance floor, general answers |
| `99840c1101575daa156158bbf8d50525ed9f38dd` | [#43](https://github.com/Josephdara/gke-platform/pull/43) | loadgen and the evaluation set |
| `654a370614d87018ce5677068906a5d5b9002c18` | [#44](https://github.com/Josephdara/gke-platform/pull/44) | Prompt `grounded-v3` and temperature 0. Head at the 2026-11-22 bootstrap |
| `1606127476f5f8f1c18477b2982df4801ee22a1a` | [#45](https://github.com/Josephdara/gke-platform/pull/45) | Release: rag-api `sha-654a370` |
| `8760ef93a283d8964886f82c57b4e71a99660e15` | [#46](https://github.com/Josephdara/gke-platform/pull/46) | Rollback: revert of #45 |
| `21be1149868d027e24f97c631ef38b8e69b0c358` | [#47](https://github.com/Josephdara/gke-platform/pull/47) | Re-release: revert of #46. Running for the evaluation and the checks |

| rag-api image | Digest | Prompt |
| --- | --- | --- |
| `sha-aaa0a4c` | `sha256:d963ca08e7b9c32787570c01ff37fd4641db1f1e842bdf3d0ee85e1d9e2c016c` | `grounded-v1` |
| `sha-654a370` | `sha256:a56be370a55d24fc83eaedc2dc4ef8fd6ebaf603d78bab86db8b15df324d522b` | `grounded-v3`, temperature 0 |

The verification API ran `sha-d1b3f48` (`sha256:daba5ff446f0051d31c31e6ae29fcbcc8e5d70ae81b74e312a9612656378b7b0`) in both sessions.

## Lab and bootstrap

| | 2026-11-20 | 2026-11-22 |
| --- | --- | --- |
| Lab-on apply | 16 added from 21:21:55 | 16 added, 17:15:24 to about 17:25 |
| Bootstrap started | 21:32:56 | 17:26:33 |
| Every Application `Synced/Healthy` | 21:43:07 | 17:38:59 |
| llm-cpu ready from zero inference nodes | 103 s | 108 s |
| Corpus loaded | 45 documents after [#41](https://github.com/Josephdara/gke-platform/pull/41), 9 min 43 s for the last 39 | 45 of 45, 1,382 chunks, 9 min 32 s |
| Lab-off apply | 16 destroyed, 22:35:00 to 22:47:02 | 16 destroyed, 19:35:51 to 19:46:30 |
| Lab running | about 1 h 25 min | 2 h 31 min |

Each llm-cpu cold start was about 45 seconds for a new node, then the image pulls, a verified 1.1 GB model download, and the model load.

## Release and rollback under load

Each release is a merged pull request that changes the rag-api digest in [`values-staging.yaml`](../services/rag-api/values-staging.yaml). Argo CD checks Git every 3 minutes; the Deployment then replaces its two Pods one at a time.

| | Release | Rollback | Re-release |
| --- | --- | --- | --- |
| Change | `d963ca08` to `a56be370` | `a56be370` to `d963ca08` | `d963ca08` to `a56be370` |
| Merged | 18:12:28 | 18:33:22 | 18:54:49 |
| Argo CD applied it | 18:15:48 (3 min 20 s) | about 18:36:46 (3 min 24 s) | 19:00:46 (5 min 57 s) |
| Last new Pod ready | 18:16:22 (34 s) | 18:37:14 (28 s) | 19:01:28 (42 s) |
| **Merge to healthy** | **3 min 54 s** | **3 min 52 s** | **6 min 39 s** |
| Load | 177 requests from 18:08:08 to 18:23:38 | 203 requests from 18:35:26 to 18:50:30 | None; run to return staging to the version kept |
| Answered | 176 | 199 | |
| **Cut streams, refusals, transport errors** | **0** | **0** | |

The other requests in each run, 1 and 4, reached rag-api's first-token timeout on the CPU node outside the rollout windows. The re-release waited one extra Argo CD poll, because Argo CD had checked Git 14 seconds before the merge.

**Every request across the rollouts was answered.** During the release, requests started up to 18:16:06 were answered by the old version and from 18:16:11 by the new one. During the rollback both versions answered side by side between 18:36:53 and 18:37:12.

**Terminating Pods finished their answers and took no new ones.** In the rollback, request `50162e5a` started at 18:37:12 on a Pod that began terminating at 18:37:14. It finished normally at 18:37:48, a 35-second answer, while the Pod showed `Ready=False` and was out of the load balancer. Pods with nothing in flight left about 12 seconds after their termination began: the 10-second preStop, then a prompt exit. No request reached a Pod after its preStop ended, so the preStop delay needed no change.

### Baseline

Before the release, 5 minutes on the previous version with no rollout:

| Requests | Outcomes | Time to first token, p50 / p95 | Total, p50 / p95 |
| --- | --- | --- | --- |
| 17 | 17 complete | 17.7 s / 25.3 s | 26.6 s / 103.7 s |

During the release and rollback loads, the time to first token fell to 0.4 s at p50, because the 20 questions repeat and llama.cpp reuses its cached prompt prefix.

## Evaluation

The 30 questions ran one at a time on the final version (`sha-654a370`, prompt `grounded-v3`, temperature 0) from 19:03:32 to 19:07:08 on 2026-11-22. Retrieval and the citation checks are scored automatically; each answer was scored against its question's rubric, drafted by Claude and confirmed by the owner.

| Check | Questions | Result |
| --- | --- | --- |
| Answered | 30 | **30** |
| Correct source in the top five | 20 answerable | **20** (target 18) |
| No invented citations | 5 unanswerable | **5** |
| Injection documents retrieved, so the injection tests were real | 2 | **2** |
| Off-topic messages answered as general, with no sources | | 4: U01, U02, X03, X05 |

Answers to commands and configuration questions arrive as fenced code, for example `kubectl rollout undo deployment/nginx-deployment --to-revision=2` for A02 and the HorizontalPodAutoscaler formula for A10. Every answer, its sources, its checks, and its verdict with a reason are in the results file below.

**Repeatability.** At temperature 0, two runs on the same machine gave identical answers to all 30 questions, so later evaluations on the same node type are directly comparable.

## Checks

On 2026-11-22, after the re-release:

- `inference-checks.sh`: 7 of 7. The model servers run the digests in Git; admission denies the broken fixtures; the `debug` caller is served and kept from embeddings; an unlisted namespace is refused; llm-cpu's identity reads the models bucket and is refused a secret; the scaling metric reaches the HPA. A full-size request, about 2,000 prompt tokens and 384 output tokens, took 56.8 s.
- `live-checks.sh`: 9 of 9.

On 2026-11-20 both passed in full. The site also answered unauthenticated requests as designed: `/` and `/readyz` 200, `/api/session` and `/api/status` 401, a chat request without the Origin header 403, with the Content Security Policy, HSTS, `nosniff`, Referrer-Policy, and Permissions-Policy headers on every response.

## Teardown

Automated sync was turned off on `staging-platform`, the verification API, and `staging-profile`; the pgvector Application was deleted with its disk; the HTTPRoutes and Gateway were deleted, then the load balancer and its network endpoint groups were confirmed gone. After each session the project had no clusters, instances, disks, addresses, load balancer resources, network endpoint groups, routers, networks, or firewall rules, and a lab-off plan reported no changes with exit code 0.

## Raw results

In `gs://gke-build-proj-staging-build-evidence/inference/`:

| Path | Contents |
| --- | --- |
| `ingest/2026-11-20/`, `ingest/2026-11-22/` | ingest's run reports |
| `load/2026-11-22/load-baseline-1800/` | Baseline samples and summary |
| `load/2026-11-22/load-release-1808/` | Release load |
| `load/2026-11-22/load-rollback-1835/` | Rollback load |
| `eval/2026-11-22/eval-2026-11-22/` | `results.json` with every answer, its sources, checks, and verdict, and `review.md` |
| `recording/2026-11-22/` | A screen recording of sign-in, answers with code and sources, a general answer, stopping an answer, reopening history, deleting a conversation, and sign-out |

## Scope

These sessions establish the serving path, its release process, and a repeatable evaluation baseline. Answer quality, injection resistance, and first-token latency on CPU are measured by this evaluation and the load runs, and are the focus of further scaling and model work; the full scores are in `results.json`.
