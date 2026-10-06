#!/usr/bin/env bash
# Validates the API tests and the shared service chart: rendering with
# Kubernetes schema checks, invalid inputs that must fail for the expected
# reason, and the admission policy fixtures. Usage: platform/tests/validate-chart.sh
# Exit codes: 0 all checks passed, 1 a check failed, 2 setup problem.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

CHART=platform/charts/service
VALUES=platform/services/platform-verification-api
FIXTURES=$CHART/tests/fixtures
APP=apps/platform-verification-api
KUBERNETES_VERSION=1.36.4
KUBECONFORM_CACHE=${KUBECONFORM_CACHE:-$HOME/.cache/kubeconform}

for tool in helm kubeconform kyverno; do
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

echo "helm $(helm version --short), kubeconform $(kubeconform -v), kyverno $(kyverno version | sed -n 's/^Version: //p'), Kubernetes schemas $KUBERNETES_VERSION"
echo

# 1. Application tests.
if [ ! -x "$APP/.venv/bin/python" ]; then
  fail "app tests: $APP/.venv is missing; create it as described in the README"
elif (cd "$APP" && .venv/bin/python -m pytest -q) > "$WORK/pytest.log" 2>&1; then
  pass "app tests: $(tail -n 1 "$WORK/pytest.log")"
else
  fail "app tests" "$WORK/pytest.log"
fi

# 2 and 3. Valid configurations must render and match the Kubernetes API schema.
# Usage: check_valid <name> <namespace> <helm values arguments...>
check_valid() {
  local name=$1 namespace=$2
  shift 2
  if ! helm template validate "$CHART" --namespace "$namespace" "$@" > "$WORK/$name.yaml" 2> "$WORK/$name.err"; then
    fail "$name: render" "$WORK/$name.err"
  elif kubeconform -strict -summary -skip SecretProviderClass,HTTPRoute -kubernetes-version "$KUBERNETES_VERSION" \
      -cache "$KUBECONFORM_CACHE" "$WORK/$name.yaml" > "$WORK/$name.kubeconform" 2>&1; then
    pass "$name: render and schema ($(tail -n 1 "$WORK/$name.kubeconform"))"
  else
    fail "$name: schema" "$WORK/$name.kubeconform"
  fi
}

check_valid staging staging -f "$VALUES/values.yaml" -f "$VALUES/values-staging.yaml"
check_valid local local -f "$VALUES/values.yaml" -f "$VALUES/values-local.yaml"

# Prints nothing when rendering fails with the expected text, otherwise the reason.
# Usage: render_fails <expected text> <helm arguments...>
render_fails() {
  local expected=$1
  shift
  if helm template validate "$CHART" "$@" > "$WORK/invalid.out" 2>&1; then
    echo "rendered, but must fail"
  elif ! grep -qF -- "$expected" "$WORK/invalid.out"; then
    echo "failed without the expected text: $expected"
  fi
}

# 4. Each invalid fixture, layered on staging, must fail with the text on its first line.
problems=""
count=0
for fixture in "$FIXTURES"/invalid/*.yaml; do
  name=$(basename "$fixture" .yaml)
  count=$((count + 1))
  expected=$(sed -n '1s/^# expect: //p' "$fixture")
  if [ -z "$expected" ]; then
    reason="no '# expect:' first line"
  else
    reason=$(render_fails "$expected" --namespace staging \
      -f "$VALUES/values.yaml" -f "$VALUES/values-staging.yaml" -f "$fixture")
  fi
  if [ -n "$reason" ]; then problems+="$name: $reason"$'\n'; fi
done
if [ -z "$problems" ]; then
  pass "invalid inputs: $count fixtures rejected"
else
  printf '%s' "$problems" > "$WORK/invalid.problems"
  fail "invalid inputs" "$WORK/invalid.problems"
fi

# 5. Rendering into another namespace must fail. The namespace is passed
# explicitly because Helm otherwise uses the kubeconfig context's namespace.
reason=$(render_fails "Target namespace mismatch" --namespace default \
  -f "$VALUES/values.yaml" -f "$VALUES/values-staging.yaml")
if [ -z "$reason" ]; then
  pass "wrong namespace refused"
elif [ "$reason" = "rendered, but must fail" ]; then
  fail "wrong namespace: $reason"
else
  fail "wrong namespace: $reason" "$WORK/invalid.out"
fi

# 6. Each policy fixture must pass or fail as platform/tests/policies/kyverno-test.yaml expects.
if kyverno test platform/tests/policies > "$WORK/kyverno.log" 2>&1; then
  pass "policy fixtures: $(grep -o '[0-9]* tests passed' "$WORK/kyverno.log")"
else
  fail "policy fixtures" "$WORK/kyverno.log"
fi

echo
echo "$passed passed, $failed failed"
[ "$failed" -eq 0 ]
