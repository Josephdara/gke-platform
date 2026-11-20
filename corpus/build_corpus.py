#!/usr/bin/env python3
"""Builds the assistant's corpus snapshot and its manifest from corpus/sources.json.

Kubernetes pages are downloaded from kubernetes/website at the pinned commit. This repository's
documents are read from Git at one commit, so the snapshot matches what that commit says, and the
synthetic documents come from the same commit. Every file's SHA-256 goes into manifest.json, and
the snapshot's revision is a hash of all of them, so the same inputs always give the same revision.

Usage: corpus/build_corpus.py [--commit <ref> [--allow-unpushed] | --working-tree] [--out <dir>]
Exit codes: 0 built, 1 a download or check failed, 2 setup problem.
"""

import argparse
import fnmatch
import hashlib
import json
from pathlib import Path
import re
import subprocess
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
FRONT_TITLE = re.compile(r"^title:\s*[\"']?(.+?)[\"']?\s*$", re.M)
H1 = re.compile(r"^#\s+(.+?)\s*$", re.M)


def git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True).stdout


def title_of(text: str, fallback: str) -> str:
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        match = FRONT_TITLE.search(text[4:end]) if end != -1 else None
        if match:
            return match.group(1)
    match = H1.search(text)
    return match.group(1) if match else fallback


def entry(path: str, data: bytes, source: str, license_: str, attribution: str) -> dict:
    return {"path": path, "title": title_of(data.decode("utf-8"), path.rsplit("/", 1)[-1]), "source": source,
            "license": license_, "attribution": attribution, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--out", default=str(ROOT / "corpus" / "build"))
    parser.add_argument("--allow-unpushed", action="store_true",
                        help="build from a commit that is not on origin/main; its source links will not resolve")
    parser.add_argument("--working-tree", action="store_true",
                        help="read this repository's files from disk, for local testing; never upload the result")
    args = parser.parse_args()
    for tool in ("git", "curl"):
        if shutil.which(tool) is None:
            print(f"Missing {tool}", file=sys.stderr)
            return 2

    if args.working_tree:
        read = lambda path: (ROOT / path).read_bytes()  # noqa: E731
        listed = lambda: [p for p in git("ls-files", "--cached", "--others", "--exclude-standard").decode().splitlines()]  # noqa: E731
        commit = "working-tree"
        return build(args, commit, read, listed())

    try:
        commit = git("rev-parse", "--verify", f"{args.commit}^{{commit}}").decode().strip()
    except subprocess.CalledProcessError:
        print(f"Unknown commit: {args.commit}", file=sys.stderr)
        return 2
    if not args.allow_unpushed and b"origin/main" not in git("branch", "-r", "--contains", commit):
        print(f"{commit[:7]} is not on origin/main, so its source links would not resolve. Push it, or pass --allow-unpushed.", file=sys.stderr)
        return 2
    tracked = git("ls-tree", "-r", "--name-only", commit).decode().splitlines()
    return build(args, commit, lambda path: git("show", f"{commit}:{path}"), tracked)


def build(args, commit: str, read, tracked: list[str]) -> int:
    sources = json.loads(read("corpus/sources.json"))
    files: dict[str, bytes] = {}
    entries: list[dict] = []

    k8s = sources["kubernetes"]
    for page in k8s["pages"]:
        url = f"https://raw.githubusercontent.com/{k8s['repository'].removeprefix('https://github.com/')}/{k8s['commit']}/{k8s['contentRoot']}/{page}"
        # curl uses the system's certificate store, which some Python builds lack.
        result = subprocess.run(["curl", "-fsSL", "--max-time", "60", url], capture_output=True)
        if result.returncode != 0:
            print(f"FAIL  {page}: curl exit {result.returncode}", file=sys.stderr)
            return 1
        data = result.stdout
        path = f"kubernetes/{page}"
        site = f"{k8s['site']}/{page.removesuffix('.md')}/"
        files[path] = data
        entries.append(entry(path, data, site, k8s["license"], k8s["attribution"]))

    repo = sources["repository"]
    paths = list(repo["paths"]) + sorted(p for p in tracked for g in repo["globs"] if fnmatch.fnmatch(p, g))
    for kind, listed, license_, attribution in (
        ("gke-platform", paths, repo["license"], repo["attribution"]),
        ("synthetic", sources["synthetic"]["paths"], sources["synthetic"]["license"], sources["synthetic"]["attribution"]),
    ):
        for path in listed:
            if path not in tracked:
                print(f"FAIL  {path}: not in {commit[:7]}", file=sys.stderr)
                return 1
            data = read(path)
            name = f"{kind}/{path.removeprefix('corpus/synthetic/')}"
            files[name] = data
            ref = "main" if commit == "working-tree" else commit
            entries.append(entry(name, data, f"{repo['url']}/blob/{ref}/{path}", license_, attribution))

    entries.sort(key=lambda e: e["path"])
    revision = hashlib.sha256("".join(f"{e['path']} {e['sha256']}\n" for e in entries).encode()).hexdigest()[:12]
    out = Path(args.out) / revision
    for path, data in files.items():
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest = {"revision": revision, "repositoryCommit": commit, "kubernetesCommit": k8s["commit"], "files": entries}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    for e in entries:
        if hashlib.sha256((out / e["path"]).read_bytes()).hexdigest() != e["sha256"]:
            print(f"FAIL  {e['path']}: written file does not match", file=sys.stderr)
            return 1
    counts = {kind: sum(e["path"].startswith(kind + "/") for e in entries) for kind in ("kubernetes", "gke-platform", "synthetic")}
    print(f"Built corpus {revision} from {commit[:12]}: {len(entries)} files {counts}, {sum(e['bytes'] for e in entries)} bytes")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
