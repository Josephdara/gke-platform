# Evidence

Reports from [lab sessions](../../infra/README.md#sessions), newest first. Each records what was run, the revisions and versions involved, the expected and actual results, and anything that was not captured.

| Date | Report | Covers |
| --- | --- | --- |
| 2026-10-07 | [Observability and acceptance tests](2026-10-07-acceptance.md) | Release D's evidence, managed Prometheus scraping, alert delivery, steady load, autoscaling, Pod failure, node drain, and a node maintenance rehearsal that did not replace any node |
| 2026-10-07 | [Admission policies, chart 1.0.0, and HTTPS](2026-10-07-admission.md) | Kyverno in Audit then Deny, mirrored controller images, HPA and PDB, HTTPS through the Gateway, and the DNS and egress re-check |
| 2026-10-06 | [Identity, secrets, and isolation](2026-10-06-isolation.md) | Mounted secrets and rotation, Google API access by identity, network isolation, quota and limits, developer RBAC |
| 2026-10-03 | [GitOps deployment](2026-10-03-gitops.md) | Argo CD bootstrap, release and rollback through pull requests, self-heal |

Run [`../tests/live-checks.sh`](../tests/live-checks.sh) during a session to repeat the non-disruptive checks.
