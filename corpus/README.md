# Corpus

The assistant answers from this corpus. [`sources.json`](sources.json) lists it:

| Part | Where it comes from | License |
| --- | --- | --- |
| 25 Kubernetes documentation pages on workloads, Services, NetworkPolicy, autoscaling, probes, resources, security, scheduling, storage, and debugging | `kubernetes/website` at a pinned commit, as Markdown | CC BY 4.0, attributed to The Kubernetes Authors |
| This repository's documentation: the READMEs, runbook, guide, architecture, and evidence reports | This repository at the commit you build from | The repository owner's documentation |
| Two synthetic documents with instructions embedded in them, in [`synthetic/`](synthetic/) | This repository | Synthetic test documents |

The synthetic documents test that the assistant treats retrieved text as reference material: an answer must never follow the instructions inside them.

## Building and uploading a snapshot

**Script, with your credentials.** [`build_corpus.py`](build_corpus.py) downloads the Kubernetes pages at the pinned commit, reads this repository's files from Git at one commit, and writes them with `manifest.json` to `corpus/build/<revision>/`. The manifest records each file's path, title, source link, license, attribution, size, and SHA-256. The revision is a hash of every path and SHA-256, so the same inputs always give the same revision. It builds only from a commit on `origin/main`, so every source link resolves.

```sh
corpus/build_corpus.py
```

[`upload-corpus.sh`](upload-corpus.sh) checks every file against the manifest again and uploads the snapshot to `corpus/<revision>/` in the models bucket. It reads `PROJECT_ID` and `ENVIRONMENT`:

```sh
corpus/upload-corpus.sh corpus/build/<revision>
```

Expect a `PASS` line for the files and the object count, which is the file count plus one for the manifest. The ingest job in the cluster reads the snapshot you point it at. For local testing, `corpus/build_corpus.py --working-tree` builds from your uncommitted files; never upload that snapshot, because its links point at `main`, not at the files you built.

To change the corpus, edit `sources.json` and build again. To move to newer Kubernetes pages, change its `commit` and check that every page still exists there.
