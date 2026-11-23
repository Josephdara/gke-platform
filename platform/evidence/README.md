# Evidence

Reports from [lab sessions](../../infra/README.md#sessions), newest first. Each records what was run, the revisions and versions involved, and the results, presents each problem with its fix, and ends with a short scope note. Raw results are in the evidence bucket.

| Date | Report | Covers |
| --- | --- | --- |
| 2026-11-22 | [CPU serving](2026-11-22-cpu-serving.md) | The assistant in staging: the full corpus loaded, a rag-api release, Git-revert rollback, and re-release in about 4 minutes from merge to healthy with no stream cut under load, graceful draining of in-flight answers, and the first scored evaluation with retrieval 20 of 20 and repeatable answers |
| 2026-11-19 | [Inference foundation](2026-11-19-inference-foundation.md) | The CPU inference pool scaling from zero, llama.cpp and TEI model servers with verified downloads, cold-start timings, inference admission policies, allowed and refused callers, Workload Identity for the models bucket, the scaling metric, service time, and three problems solved during the session |
| 2026-10-07 | [Observability and acceptance tests](2026-10-07-acceptance.md) | Release D's evidence, managed Prometheus scraping, alert delivery, steady load, autoscaling, Pod failure, and node drain |
| 2026-10-07 | [Admission policies, chart 1.0.0, and HTTPS](2026-10-07-admission.md) | Kyverno in Audit then Deny, mirrored controller images, HPA and PDB, HTTPS through the Gateway, and the DNS and egress re-check |
| 2026-10-06 | [Identity, secrets, and isolation](2026-10-06-isolation.md) | Mounted secrets and rotation, Google API access by identity, network isolation, quota and limits, developer RBAC |
| 2026-10-03 | [GitOps deployment](2026-10-03-gitops.md) | Argo CD bootstrap, release and rollback through pull requests, self-heal |

Run [`../tests/live-checks.sh`](../tests/live-checks.sh) during a session to repeat the non-disruptive checks, and [`../tests/inference-checks.sh`](../tests/inference-checks.sh) in a session with the inference pool.
