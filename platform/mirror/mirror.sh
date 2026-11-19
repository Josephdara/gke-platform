#!/usr/bin/env bash
# Copies every image in images.yaml unchanged into the mirror repository,
# confirms the copy kept its pinned digest, scans it with Trivy, and uploads
# the scan report to the evidence bucket. Run it with your own credentials.
# Usage: platform/mirror/mirror.sh          copy, scan, and upload
#        platform/mirror/mirror.sh --check  compare upstream tags with the pinned digests,
#                                           and fail on a missing or expired scan decision
# Settings: PROJECT_ID, REGION, ENVIRONMENT (defaults gke-build-proj, us-east4, staging).
# Exit codes: 0 done, 1 a copy, digest, scan, or upload failed, 2 setup problem.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

PROJECT_ID=${PROJECT_ID:-gke-build-proj}
REGION=${REGION:-us-east4}
ENVIRONMENT=${ENVIRONMENT:-staging}
MIRROR=$REGION-docker.pkg.dev/$PROJECT_ID/$ENVIRONMENT-mirror
REPORTS=gs://$PROJECT_ID-$ENVIRONMENT-build-evidence/inference/mirror
MODE=${1:-copy}

tools="crane"
[ "$MODE" = "--check" ] || tools="crane trivy gcloud"
for tool in $tools; do
  command -v "$tool" >/dev/null 2>&1 || { echo "Missing $tool" >&2; exit 2; }
done

# Prints source|digest|target|reviewBy for each entry.
entries() {
  awk '
    function emit() { if (src != "") print src "|" dig "|" tgt "|" rev }
    $1 == "-" && $2 == "source:" { emit(); src = $3; dig = ""; tgt = ""; rev = "" }
    $1 == "digest:" { dig = $2 }
    $1 == "target:" { tgt = $2 }
    $1 == "reviewBy:" { rev = $2 }
    END { emit() }
  ' images.yaml
}

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
failed=0
date=$(date -u +%Y-%m-%d)

while IFS='|' read -r src digest target review; do
  repo=${src%:*}
  if [ "$MODE" = "--check" ]; then
    if [ -z "$review" ]; then
      echo "FAIL  $src  has no scan decision; scan it and add one"; failed=1
    elif [ "$review" \< "$date" ]; then
      echo "FAIL  $src  scan decision expired on $review; scan again and redo the decision"; failed=1
    fi
    current=$(crane digest "$src" 2>/dev/null || echo unknown)
    if ! crane digest "$repo@$digest" >/dev/null 2>&1; then
      echo "FAIL  $src  pinned digest no longer exists upstream"; failed=1
    elif [ "$current" = "$digest" ]; then
      echo "PASS  $src  tag still points to the pinned digest"
    else
      echo "NOTE  $src  tag now points to $current; the pinned digest still exists"
    fi
    continue
  fi

  echo "== $target"
  if ! crane copy "$repo@$digest" "$MIRROR/$target"; then
    echo "FAIL  copy $src" >&2; failed=1; continue
  fi
  copied=$(crane digest "$MIRROR/$target")
  if [ "$copied" != "$digest" ]; then
    echo "FAIL  $MIRROR/$target has $copied, expected $digest" >&2; failed=1; continue
  fi
  report="$WORK/$(echo "$target" | tr '/:' '__').json"
  # Serving images are not gated on the scan; findings get a recorded decision.
  if ! trivy image --quiet --format json --output "$report" "$MIRROR/$target@$digest"; then
    echo "FAIL  scan $target" >&2; failed=1; continue
  fi
  if ! gcloud storage cp --quiet "$report" "$REPORTS/$date/$(basename "$report")"; then
    echo "FAIL  upload scan report for $target" >&2; failed=1; continue
  fi
  echo "PASS  $digest  $MIRROR/$target"
done < <(entries)

exit "$failed"
