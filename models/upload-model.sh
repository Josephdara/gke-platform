#!/usr/bin/env bash
# Downloads one model's files from Hugging Face at the manifest's pinned
# revision, checks every file's size and SHA-256 against the manifest, and only
# then uploads them to the models bucket. Run it with your own credentials.
# Usage: models/upload-model.sh models/<name>.yaml
# Settings: PROJECT_ID, ENVIRONMENT (defaults gke-build-proj, staging), and
#   MODEL_CACHE, where downloads are kept (default ~/.cache/gke-platform-models).
# Exit codes: 0 uploaded, 1 a download, check, or upload failed, 2 setup problem.
set -euo pipefail

MANIFEST=${1:-}
[ -f "$MANIFEST" ] || { echo "Usage: $0 models/<name>.yaml" >&2; exit 2; }
for tool in curl shasum gcloud; do
  command -v "$tool" >/dev/null 2>&1 || { echo "Missing $tool" >&2; exit 2; }
done

PROJECT_ID=${PROJECT_ID:-gke-build-proj}
ENVIRONMENT=${ENVIRONMENT:-staging}
BUCKET=gs://$PROJECT_ID-$ENVIRONMENT-models

field() { awk -v k="$1:" '$1 == k { print $2; exit }' "$MANIFEST"; }
repo=$(field sourceRepository)
revision=$(field sourceRevision)
prefix=$(field bucketPath)
name=$(field name)
[ -n "$repo" ] && [ -n "$revision" ] && [ -n "$prefix" ] || { echo "Manifest is missing sourceRepository, sourceRevision, or bucketPath" >&2; exit 2; }

CACHE=${MODEL_CACHE:-$HOME/.cache/gke-platform-models}/$name/$revision
mkdir -p "$CACHE"

# Prints path|size|sha256 for each file.
files() {
  awk '
    $1 == "-" && $2 == "path:" { p = $3 }
    $1 == "sizeBytes:" { s = $2 }
    $1 == "sha256:" { print p "|" s "|" $2 }
  ' "$MANIFEST"
}

failed=0
while IFS='|' read -r path size sha; do
  local_file="$CACHE/$path"
  mkdir -p "$(dirname "$local_file")"
  if [ ! -f "$local_file" ]; then
    echo "== download $path"
    curl -fL --retry 3 -o "$local_file.part" "https://huggingface.co/$repo/resolve/$revision/$path"
    mv "$local_file.part" "$local_file"
  fi
  actual_size=$(wc -c < "$local_file" | tr -d ' ')
  actual_sha=$(shasum -a 256 "$local_file" | cut -d' ' -f1)
  if [ "$actual_size" = "$size" ] && [ "$actual_sha" = "$sha" ]; then
    echo "PASS  $path  $sha"
  else
    echo "FAIL  $path  size $actual_size (expected $size), sha256 $actual_sha (expected $sha)" >&2
    failed=1
  fi
done < <(files)

if [ "$failed" -ne 0 ]; then
  echo "Nothing uploaded: a file does not match the manifest. Delete it from $CACHE and rerun." >&2
  exit 1
fi

echo "== upload to $BUCKET/$prefix"
while IFS='|' read -r path size sha; do
  gcloud storage cp --quiet "$CACHE/$path" "$BUCKET/$prefix$path"
done < <(files)
gcloud storage ls -l "$BUCKET/$prefix**"
