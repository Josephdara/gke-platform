#!/usr/bin/env bash
# Validates the API tests and both charts (the shared service chart and the
# model-server chart): rendering with Kubernetes schema checks, invalid inputs
# that must fail for the expected reason, the schema of the pgvector manifests,
# model values that must match their manifests, and the admission policy
# fixtures, every one of which must be evaluated. Usage: platform/tests/validate-chart.sh
# Set SKIP_APP_TESTS=1 to skip the application tests.
# Exit codes: 0 all checks passed, 1 a check failed, 2 setup problem.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

CHART=platform/charts/service
VALUES=platform/services/platform-verification-api
FIXTURES=$CHART/tests/fixtures
MODEL_CHART=platform/charts/model-server
MODEL_SERVICES="llm-cpu embeddings"
MANIFEST_DIRS="platform/services/pgvector"
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

# 1. Application tests. CI sets SKIP_APP_TESTS because its own test step runs them.
if [ -n "${SKIP_APP_TESTS:-}" ]; then
  printf 'SKIP  app tests: SKIP_APP_TESTS is set\n'
elif [ ! -x "$APP/.venv/bin/python" ]; then
  fail "app tests: $APP/.venv is missing; create it as described in the README"
elif (cd "$APP" && .venv/bin/python -m pytest -q) > "$WORK/pytest.log" 2>&1; then
  pass "app tests: $(tail -n 1 "$WORK/pytest.log")"
else
  fail "app tests" "$WORK/pytest.log"
fi

# 2. Valid configurations must render and match the Kubernetes API schema.
# Usage: check_valid <name> <chart> <namespace> <helm values arguments...>
check_valid() {
  local name=$1 chart=$2 namespace=$3
  shift 3
  if ! helm template validate "$chart" --namespace "$namespace" "$@" > "$WORK/$name.yaml" 2> "$WORK/$name.err"; then
    fail "$name: render" "$WORK/$name.err"
  elif kubeconform -strict -summary -skip SecretProviderClass,HTTPRoute,PodMonitoring -kubernetes-version "$KUBERNETES_VERSION" \
      -cache "$KUBECONFORM_CACHE" "$WORK/$name.yaml" > "$WORK/$name.kubeconform" 2>&1; then
    pass "$name: render and schema ($(tail -n 1 "$WORK/$name.kubeconform"))"
  else
    fail "$name: schema" "$WORK/$name.kubeconform"
  fi
}

check_valid staging "$CHART" staging -f "$VALUES/values.yaml" -f "$VALUES/values-staging.yaml"
check_valid local "$CHART" local -f "$VALUES/values.yaml" -f "$VALUES/values-local.yaml"
for service in $MODEL_SERVICES; do
  check_valid "$service" "$MODEL_CHART" staging-inference \
    -f "platform/services/$service/values.yaml" -f "platform/services/$service/values-staging.yaml"
done

# Plain manifests, applied by Argo CD through Kustomize.
for dir in $MANIFEST_DIRS; do
  name=$(basename "$dir")
  if kubeconform -strict -summary -skip SecretProviderClass -ignore-filename-pattern 'kustomization[.]yaml' \
      -kubernetes-version "$KUBERNETES_VERSION" -cache "$KUBECONFORM_CACHE" "$dir" > "$WORK/$name.kubeconform" 2>&1; then
    pass "$name: schema ($(tail -n 1 "$WORK/$name.kubeconform"))"
  else
    fail "$name: schema" "$WORK/$name.kubeconform"
  fi
done

# Prints nothing when rendering fails with the expected text, otherwise the reason.
# Usage: render_fails <chart> <expected text> <helm arguments...>
render_fails() {
  local chart=$1 expected=$2
  shift 2
  if helm template validate "$chart" "$@" > "$WORK/invalid.out" 2>&1; then
    echo "rendered, but must fail"
  elif ! grep -qF -- "$expected" "$WORK/invalid.out"; then
    echo "failed without the expected text: $expected"
  fi
}

# 3. Each invalid fixture, layered on a valid configuration, must fail with the
# text on its first line. Usage: check_invalid <label> <chart> <namespace> <values dir>
check_invalid() {
  local label=$1 chart=$2 namespace=$3 values=$4 problems="" count=0 fixture name expected reason
  for fixture in "$chart"/tests/fixtures/invalid/*.yaml; do
    name=$(basename "$fixture" .yaml)
    count=$((count + 1))
    expected=$(sed -n '1s/^# expect: //p' "$fixture")
    if [ -z "$expected" ]; then
      reason="no '# expect:' first line"
    else
      reason=$(render_fails "$chart" "$expected" --namespace "$namespace" \
        -f "$values/values.yaml" -f "$values/values-staging.yaml" -f "$fixture")
    fi
    if [ -n "$reason" ]; then problems+="$name: $reason"$'\n'; fi
  done
  if [ -z "$problems" ]; then
    pass "$label invalid inputs: $count fixtures rejected"
  else
    printf '%s' "$problems" > "$WORK/invalid.problems"
    fail "$label invalid inputs" "$WORK/invalid.problems"
  fi
}

check_invalid "service chart" "$CHART" staging "$VALUES"
check_invalid "model-server chart" "$MODEL_CHART" staging-inference platform/services/llm-cpu

# 4. Rendering into another namespace must fail. The namespace is passed
# explicitly because Helm otherwise uses the kubeconfig context's namespace.
reason=$(render_fails "$CHART" "Target namespace mismatch" --namespace default \
  -f "$VALUES/values.yaml" -f "$VALUES/values-staging.yaml")
if [ -z "$reason" ]; then
  pass "wrong namespace refused"
elif [ "$reason" = "rendered, but must fail" ]; then
  fail "wrong namespace: $reason"
else
  fail "wrong namespace: $reason" "$WORK/invalid.out"
fi

# 5. Each model server's values must name the same revision, bucket path, and
# files (path, size, SHA-256) as its manifest in models/.
# Prints the comparable fields of a values file or a model manifest.
model_fields() {
  awk '
    $1 == "revision:" || $1 == "sourceRevision:" { print "revision " $2 }
    $1 == "bucketPath:" { print "bucketPath " $2 }
    $1 == "-" && $2 == "path:" { p = $3 }
    $1 == "sizeBytes:" { s = $2 }
    $1 == "sha256:" { print "file " p " " s " " $2 }
  ' "$1" | sort
}
problems=""
for service in $MODEL_SERVICES; do
  values=platform/services/$service/values.yaml
  model=$(awk '$1 == "name:" && prev == "model:" { print $2; exit } { prev = $1 }' "$values")
  manifest=models/$model.yaml
  if [ ! -f "$manifest" ]; then
    problems+="$service: no manifest $manifest"$'\n'
  elif ! diff <(model_fields "$values") <(model_fields "$manifest") > "$WORK/model-$service.diff"; then
    problems+="$service: values differ from $manifest"$'\n'"$(cat "$WORK/model-$service.diff")"$'\n'
  fi
done
if [ -z "$problems" ]; then
  pass "model values match their manifests"
else
  printf '%s' "$problems" > "$WORK/model.problems"
  fail "model values match their manifests" "$WORK/model.problems"
fi

# 6. Each policy fixture must pass or fail as platform/tests/policies/kyverno-test.yaml
# expects, and every expected result must be evaluated. The Kyverno CLI counts a
# policy that does not match a fixture's namespace as a pass, so the evaluated
# results are counted against the expected ones.
if kyverno test platform/tests/policies --detailed-results > "$WORK/kyverno.log" 2>&1; then
  expected=$(grep -c '^  - policy:' platform/tests/policies/kyverno-test.yaml)
  evaluated=$(sed 's/\x1b\[[0-9;]*m//g' "$WORK/kyverno.log" | awk -F'│' '$7 ~ /^ *Ok *$/' | wc -l | tr -d ' ')
  if [ "$evaluated" -eq "$expected" ]; then
    pass "policy fixtures: $(grep -o '[0-9]* tests passed' "$WORK/kyverno.log"), $evaluated of $expected results evaluated"
  else
    # Lists each expected policy and resource pair that has no evaluated result.
    awk '$1 == "-" && $2 == "policy:" { p = $3 } $1 == "resources:" { gsub(/[][,]/, " "); for (i = 2; i <= NF; i++) print p, $i }' \
      platform/tests/policies/kyverno-test.yaml | sort -u > "$WORK/kyverno.expected"
    sed 's/\x1b\[[0-9;]*m//g' "$WORK/kyverno.log" | awk -F'│' '$7 ~ /^ *Ok *$/ { gsub(/ /, "", $3); n = split($5, r, "/"); gsub(/ /, "", r[n]); print $3, r[n] }' \
      | sort -u > "$WORK/kyverno.evaluated"
    comm -23 "$WORK/kyverno.expected" "$WORK/kyverno.evaluated" | sed 's/^/not evaluated: /' > "$WORK/kyverno.missing"
    fail "policy fixtures: only $evaluated of $expected expected results were evaluated; a policy does not cover a fixture's namespace" "$WORK/kyverno.missing"
  fi
else
  fail "policy fixtures" "$WORK/kyverno.log"
fi

echo
echo "$passed passed, $failed failed"
[ "$failed" -eq 0 ]
