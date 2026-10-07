#!/usr/bin/env bash
# Non-disruptive checks against the staging lab cluster: GitOps health, the
# running image, the mounted secret, network isolation, admission, developer
# access, and HTTPS. It creates one short-lived namespace and always deletes it.
# Usage: platform/tests/live-checks.sh
# Exit codes: 0 all checks passed, 1 a check failed, 2 setup problem.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

CONTEXT=${CONTEXT:-gke_gke-build-proj_us-east4-b_staging-super-cluster}
APP=staging-platform-verification-api
VALUES=platform/services/platform-verification-api/values-staging.yaml
CHECK_NS=live-check-$$

k() { kubectl --context "$CONTEXT" "$@"; }

for tool in kubectl git curl; do
  command -v "$tool" >/dev/null 2>&1 || { echo "Missing $tool" >&2; exit 2; }
done
if ! k get namespace kube-system >/dev/null 2>&1; then
  echo "Cannot reach context $CONTEXT. Run get-credentials first." >&2
  exit 2
fi
trap 'k delete namespace "$CHECK_NS" --ignore-not-found --wait=false >/dev/null 2>&1' EXIT

passed=0
failed=0
# Usage: check <description> <function>. The function's output is shown under the result.
check() {
  local output
  if output=$("$2" 2>&1); then
    passed=$((passed + 1)); printf 'PASS  %s\n' "$1"
  else
    failed=$((failed + 1)); printf 'FAIL  %s\n' "$1"
  fi
  printf '%s\n' "$output" | sed '/^$/d; s/^/      /' | tail -n 8
}

applications_healthy() {
  local status
  status=$(k -n argocd get applications.argoproj.io \
    -o jsonpath='{range .items[*]}{.metadata.name} {.status.sync.status}/{.status.health.status}{"\n"}{end}')
  echo "$status"
  [ -n "$status" ] && ! echo "$status" | grep -qv ' Synced/Healthy$'
}

image_matches_git() {
  local revision expected running
  revision=$(k -n argocd get applications.argoproj.io "$APP" -o jsonpath='{.status.sync.revision}')
  git fetch --quiet origin main || true
  expected=$(git show "$revision:$VALUES" 2>/dev/null | sed -n 's/^ *digest: "\(sha256:[0-9a-f]*\)".*/\1/p')
  running=$(k -n staging get pods -l app.kubernetes.io/instance="$APP" \
    -o jsonpath='{range .items[*]}{.status.containerStatuses[0].imageID}{"\n"}{end}' \
    | sed -n 's/.*@\(sha256:[0-9a-f]*\)$/\1/p' | sort -u)
  echo "revision ${revision:0:7}, expected ${expected:-unknown}, running ${running:-none}"
  [ -n "$expected" ] && [ "$running" = "$expected" ]
}

secret_label_served() {
  k -n staging exec deploy/"$APP" -- python -c 'import json, urllib.request
label = json.load(urllib.request.urlopen("http://127.0.0.1:8080/"))["secretLabel"]
print("secretLabel", label)
assert label'
}

dns_without_egress() {
  k -n staging exec deploy/"$APP" -- python -c 'import socket, sys
print("dns", socket.gethostbyname("secretmanager.googleapis.com"))
try:
    socket.create_connection(("secretmanager.googleapis.com", 443), timeout=5)
except OSError as error:
    print("egress blocked", type(error).__name__)
else:
    sys.exit("egress connected")'
}

other_namespace_refused() {
  local image rc
  image=$(k -n staging get deployment "$APP" -o jsonpath='{.spec.template.spec.containers[0].image}')
  k create namespace "$CHECK_NS" >/dev/null || return 1
  k -n "$CHECK_NS" run net-check --image="$image" --restart=Never --command -- python -c 'import socket, sys
try:
    socket.create_connection(("staging-platform-verification-api.staging.svc.cluster.local", 80), timeout=5)
except OSError as error:
    print("API blocked", type(error).__name__)
else:
    sys.exit("API reachable")
socket.create_connection(("www.google.com", 443), timeout=5).close()
print("internet connected")' >/dev/null || return 1
  k -n "$CHECK_NS" wait --for=jsonpath='{.status.phase}'=Succeeded pod/net-check --timeout=120s >/dev/null
  rc=$?
  k -n "$CHECK_NS" logs net-check
  return $rc
}

naive_deployment_denied() {
  local output
  output=$(k -n staging create deployment live-check --image=docker.io/library/nginx:latest --dry-run=server 2>&1)
  echo "$output" | grep -o 'Policy [a-z-]* failed' | sort -u
  echo "$output" | grep -q 'denied the request'
}

naive_deployment_allowed_elsewhere() {
  k -n default create deployment live-check --image=docker.io/library/nginx:latest --dry-run=server
}

developer_read_only() {
  local as=(--as=live-check --as-group=staging-developers -n staging)
  echo "list pods: $(k auth can-i list pods "${as[@]}"), get secrets: $(k auth can-i get secrets "${as[@]}"), create pods/exec: $(k auth can-i create pods/exec "${as[@]}")"
  k auth can-i list pods "${as[@]}" >/dev/null && ! k auth can-i get secrets "${as[@]}" >/dev/null \
    && ! k auth can-i create pods/exec "${as[@]}" >/dev/null
}

https_answers() {
  local host code
  host=$(sed -n 's/^ *hostname: *//p' "$VALUES")
  [ -n "$host" ] || { echo "no httpRoute.hostname in $VALUES"; return 1; }
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "https://$host/")
  echo "https://$host/ HTTP $code"
  [ "$code" = 200 ]
}

echo "Live checks, $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "  Local HEAD:  $(git rev-parse --short HEAD)"
echo "  Kubernetes:  $(k get nodes -o jsonpath='{.items[0].status.nodeInfo.kubeletVersion}') on $(k get nodes --no-headers | wc -l | tr -d ' ') nodes"
echo "  Argo CD:     $(k -n argocd get statefulset argocd-application-controller -o jsonpath='{.spec.template.spec.containers[0].image}' | sed 's/.*:\(v[^@]*\)@.*/\1/')"
echo "  Kyverno:     $(k -n kyverno get deployment kyverno-admission-controller -o jsonpath='{.spec.template.spec.containers[0].image}' | sed 's/.*:\(v[^@]*\)@.*/\1/')"
echo

check "Applications Synced and Healthy" applications_healthy
check "running image matches Git" image_matches_git
check "API serves its mounted secret's label" secret_label_served
check "DNS resolves and outbound connections are refused" dns_without_egress
check "a Pod in another namespace cannot reach the API" other_namespace_refused
check "admission denies a naive Deployment in staging" naive_deployment_denied
check "admission ignores the same Deployment outside staging" naive_deployment_allowed_elsewhere
check "developers are read-only in staging" developer_read_only
check "HTTPS through the Gateway answers 200" https_answers

echo
echo "$passed passed, $failed failed"
[ "$failed" -eq 0 ]
