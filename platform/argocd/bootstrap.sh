#!/usr/bin/env bash
# Installs Argo CD and the root Application on the staging cluster, then waits
# until every Application is Synced and Healthy. Safe to rerun.
# Usage: platform/argocd/bootstrap.sh
# Exit codes: 0 done, 1 a step failed or timed out, 2 setup problem.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

CONTEXT=${CONTEXT:-gke_gke-build-proj_us-east4-b_staging-super-cluster}
APPS="staging-platform staging-platform-verification-api"
VALUES=platform/services/platform-verification-api/values-staging.yaml
TIMEOUT=${TIMEOUT:-600}

k() { kubectl --context "$CONTEXT" "$@"; }

for tool in kubectl git; do
  command -v "$tool" >/dev/null 2>&1 || { echo "Missing $tool" >&2; exit 2; }
done
if ! k get namespace kube-system >/dev/null 2>&1; then
  echo "Cannot reach context $CONTEXT. Run get-credentials first." >&2
  exit 2
fi

echo "== Installing Argo CD"
k apply --server-side --force-conflicts -k platform/argocd
k wait --for=condition=Established --timeout=120s \
  crd/applications.argoproj.io crd/applicationsets.argoproj.io crd/appprojects.argoproj.io
k -n argocd rollout status statefulset/argocd-application-controller --timeout=300s
for d in argocd-repo-server argocd-redis argocd-applicationset-controller; do
  k -n argocd rollout status "deployment/$d" --timeout=300s
done

echo "== Applying the root Application"
k apply --server-side --force-conflicts -f platform/argocd/root/

echo "== Waiting up to ${TIMEOUT}s for Applications to be Synced and Healthy"
deadline=$(( $(date +%s) + TIMEOUT ))
while :; do
  ready=0
  for app in $APPS; do
    state=$(k -n argocd get applications.argoproj.io "$app" \
      -o jsonpath='{.status.sync.status}/{.status.health.status}' 2>/dev/null || true)
    printf '  %-36s %s\n' "$app" "${state:-not created yet}"
    if [ "$state" = "Synced/Healthy" ]; then ready=$((ready + 1)); fi
  done
  if [ "$ready" -eq 2 ]; then break; fi
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "Timed out. Inspect with: kubectl --context $CONTEXT -n argocd get applications" >&2
    exit 1
  fi
  sleep 15
done

echo "== Versions and running image"
argocd_image=$(k -n argocd get statefulset argocd-application-controller \
  -o jsonpath='{.spec.template.spec.containers[0].image}')
helm_version=$(k -n argocd exec deploy/argocd-repo-server -c argocd-repo-server -- helm version --short || echo unknown)
revision=$(k -n argocd get applications.argoproj.io staging-platform-verification-api \
  -o jsonpath='{.status.sync.revision}')
git fetch --quiet origin main || true
expected=$(git show "$revision:$VALUES" 2>/dev/null | sed -n 's/^ *digest: "\(sha256:[0-9a-f]*\)".*/\1/p' || true)
running=$(k -n staging get pods \
  -o go-template='{{range .items}}{{if not .metadata.deletionTimestamp}}{{(index .status.containerStatuses 0).imageID}}{{"\n"}}{{end}}{{end}}' \
  | sed -n 's/.*@\(sha256:[0-9a-f]*\)$/\1/p' | sort -u)

echo "  Argo CD image:    $argocd_image"
echo "  Bundled Helm:     $helm_version"
echo "  Synced revision:  $revision"
echo "  Expected digest:  ${expected:-unknown}"
echo "  Running digests:  $(echo "$running" | tr '\n' ' ')"

if [ -n "$expected" ] && [ "$running" = "$expected" ]; then
  echo "PASS  running image matches Git"
else
  echo "FAIL  running image does not match Git" >&2
  exit 1
fi
