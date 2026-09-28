#!/usr/bin/env bash
# Validates the API tests and the shared service chart: lint, rendering,
# Kubernetes schema checks, and invalid fixtures that must fail for the
# expected reason. Usage: platform/tests/validate-chart.sh
# Exit codes: 0 all checks passed, 1 a check failed, 2 setup problem.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

CHART=platform/charts/service
VALUES=platform/services/platform-verification-api
FIXTURES=$CHART/tests/fixtures
APP=apps/platform-verification-api
# Assumed cluster version until the GKE version is known; matches Docker Desktop.
KUBERNETES_VERSION=1.36.1
KUBECONFORM_CACHE=${KUBECONFORM_CACHE:-$HOME/.cache/kubeconform}

for tool in helm kubeconform; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Missing $tool. Install it with: brew install $tool" >&2
    exit 2
  fi
done
mkdir -p "$KUBECONFORM_CACHE"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

passed=0
failed=0
pass() { passed=$((passed + 1)); printf 'PASS  %s\n' "$1"; }
fail() {
  failed=$((failed + 1))
  printf 'FAIL  %s\n' "$1"
  if [ -n "${2:-}" ]; then sed 's/^/      /' "$2" | tail -n 20; fi
}

echo "helm $(helm version --short), kubeconform $(kubeconform -v), Kubernetes schemas $KUBERNETES_VERSION"
echo

# Application tests.
if [ ! -x "$APP/.venv/bin/python" ]; then
  fail "app tests: $APP/.venv is missing; create it as described in the README"
elif (cd "$APP" && .venv/bin/python -m pytest -q) > "$WORK/pytest.log" 2>&1; then
  pass "app tests: $(tail -n 1 "$WORK/pytest.log")"
else
  fail "app tests" "$WORK/pytest.log"
fi

# Valid configurations must lint, render, and match the Kubernetes API schema.
# Usage: check_valid <name> <namespace> <helm values arguments...>
check_valid() {
  local name=$1 namespace=$2
  shift 2
  if helm lint "$CHART" --namespace "$namespace" "$@" > "$WORK/$name.lint" 2>&1; then
    pass "lint: $name"
  else
    fail "lint: $name" "$WORK/$name.lint"
  fi
  if ! helm template validate "$CHART" --namespace "$namespace" "$@" > "$WORK/$name.yaml" 2> "$WORK/$name.err"; then
    fail "render: $name" "$WORK/$name.err"
    return
  fi
  pass "render: $name"
  if kubeconform -strict -summary -kubernetes-version "$KUBERNETES_VERSION" \
      -cache "$KUBECONFORM_CACHE" "$WORK/$name.yaml" > "$WORK/$name.kubeconform" 2>&1; then
    pass "kubeconform: $name ($(tail -n 1 "$WORK/$name.kubeconform"))"
  else
    fail "kubeconform: $name" "$WORK/$name.kubeconform"
  fi
}

check_valid api-staging gke-build-proj-staging -f "$VALUES/values.yaml" -f "$VALUES/values-staging.yaml"
check_valid api-local gke-build-proj-local -f "$VALUES/values.yaml" -f "$VALUES/values-local.yaml"
check_valid second-service gke-build-proj-staging -f "$FIXTURES/valid/second-service.yaml"

# Invalid configurations must fail, and the error must contain the expected text.
# Usage: check_invalid <name> <expected text> <helm arguments...>
check_invalid() {
  local name=$1 expected=$2
  shift 2
  if helm template validate "$CHART" "$@" > "$WORK/invalid.out" 2>&1; then
    fail "invalid: $name rendered, but must fail"
  elif grep -qF -- "$expected" "$WORK/invalid.out"; then
    pass "invalid: $name"
  else
    fail "invalid: $name failed without the expected text: $expected" "$WORK/invalid.out"
  fi
}

for fixture in "$FIXTURES"/invalid/*.yaml; do
  name=$(basename "$fixture" .yaml)
  expected=$(sed -n '1s/^# expect: //p' "$fixture")
  if [ -z "$expected" ]; then
    fail "invalid: $name has no '# expect:' first line"
    continue
  fi
  check_invalid "$name" "$expected" --namespace gke-build-proj-staging \
    -f "$VALUES/values.yaml" -f "$VALUES/values-staging.yaml" -f "$fixture"
done

# Cases a values overlay cannot express. The namespace is passed explicitly
# because Helm otherwise uses the kubeconfig context's namespace.
check_invalid wrong-namespace "Target namespace mismatch" --namespace default \
  -f "$VALUES/values.yaml" -f "$VALUES/values-staging.yaml"
check_invalid shared-values-alone "missing properties" --namespace gke-build-proj-staging \
  -f "$VALUES/values.yaml"

echo
echo "$passed passed, $failed failed"
[ "$failed" -eq 0 ]
