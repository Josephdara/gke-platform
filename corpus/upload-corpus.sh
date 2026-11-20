#!/usr/bin/env bash
# Checks every file in a built corpus snapshot against its manifest, then uploads the snapshot
# to corpus/<revision>/ in the models bucket. Run it with your own credentials.
# Usage: corpus/upload-corpus.sh corpus/build/<revision>
# Settings: PROJECT_ID, ENVIRONMENT (defaults gke-build-proj, staging).
# Exit codes: 0 uploaded, 1 a check or the upload failed, 2 setup problem.
set -euo pipefail

DIR=${1:-}
[ -f "$DIR/manifest.json" ] || { echo "Usage: $0 corpus/build/<revision>" >&2; exit 2; }
for tool in python3 gcloud; do
  command -v "$tool" >/dev/null 2>&1 || { echo "Missing $tool" >&2; exit 2; }
done

PROJECT_ID=${PROJECT_ID:-gke-build-proj}
ENVIRONMENT=${ENVIRONMENT:-staging}
revision=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["revision"])' "$DIR/manifest.json")
[ "$(basename "$DIR")" = "$revision" ] || { echo "Directory name does not match the manifest revision $revision" >&2; exit 2; }
TARGET=gs://$PROJECT_ID-$ENVIRONMENT-models/corpus/$revision/

python3 - "$DIR" <<'PY' || exit 1
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
manifest = json.loads((root / "manifest.json").read_text())
bad = [f["path"] for f in manifest["files"]
       if hashlib.sha256((root / f["path"]).read_bytes()).hexdigest() != f["sha256"]]
for path in bad:
    print(f"FAIL  {path}: does not match the manifest", file=sys.stderr)
print(f"PASS  {len(manifest['files']) - len(bad)} of {len(manifest['files'])} files match the manifest")
sys.exit(1 if bad else 0)
PY

gcloud storage cp --recursive "$DIR/*" "$TARGET" --project="$PROJECT_ID"
echo "Uploaded corpus $revision to $TARGET"
gcloud storage ls --recursive "$TARGET" --project="$PROJECT_ID" | grep -c -v '/$' | xargs echo "Objects:"
