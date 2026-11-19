#!/usr/bin/env bash
# Checks the inference namespace on the staging lab cluster: model server
# admission, the allowed and refused callers, Workload Identity, and the scaling
# metric. RECORD lines are measurements for the evidence report (cold-start
# timings, service time, admission cap) and never fail the run. Run it within
# an hour of the llm-cpu Pod starting, before its image-pull events expire.
# It creates short-lived test Pods, a namespace and the staging-debug service
# account, and always deletes them.
# Usage: platform/tests/inference-checks.sh
# Exit codes: 0 all checks passed, 1 a check failed, 2 setup problem.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

CONTEXT=${CONTEXT:-gke_gke-build-proj_us-east4-a_staging-super-cluster}
INFER_NS=staging-inference
RUN=inference-check-$$
CHECK_NS=$RUN
DEBUG_SA=staging-debug
API_APP=staging-platform-verification-api
API_VALUES=platform/services/platform-verification-api/values-staging.yaml
LLM_VALUES=platform/services/llm-cpu/values.yaml
FIXTURES=platform/tests/policies/deployments.yaml
EXPECTED=platform/tests/policies/kyverno-test.yaml
LLM_HOST=staging-llm-cpu.$INFER_NS.svc.cluster.local
EMBED_HOST=staging-embeddings.$INFER_NS.svc.cluster.local
# rag-api's request deadline, which the admission cap is measured against.
DEADLINE_SECONDS=120
METRIC='prometheus.googleapis.com|llamacpp:requests_deferred|gauge'

k() { kubectl --context "$CONTEXT" "$@"; }

for tool in kubectl git awk; do
  command -v "$tool" >/dev/null 2>&1 || { echo "Missing $tool" >&2; exit 2; }
done
if ! k get namespace kube-system >/dev/null 2>&1; then
  echo "Cannot reach context $CONTEXT. Run get-credentials first." >&2
  exit 2
fi
cleanup() {
  k delete pods -A -l inference-check="$RUN" --ignore-not-found --wait=false >/dev/null 2>&1
  k -n staging delete serviceaccount "$DEBUG_SA" --ignore-not-found >/dev/null 2>&1
  k delete namespace "$CHECK_NS" --ignore-not-found --wait=false >/dev/null 2>&1
}
trap cleanup EXIT

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
# Usage: record <description> <function>. Measurements only: never counted.
record() {
  printf 'RECORD %s\n' "$1"
  "$2" 2>&1 | sed '/^$/d; s/^/      /'
}

# Seconds since the epoch for an RFC 3339 time, with GNU or BSD date.
epoch() {
  local t=${1%%.*}; t=${t%Z}
  date -u -d "${t}Z" +%s 2>/dev/null || date -u -j -f '%Y-%m-%dT%H:%M:%S' "$t" +%s 2>/dev/null
}
# Usage: since <start epoch> <RFC 3339 time>. Prints +<n>s, or "unknown".
since() {
  local end
  [ -n "$2" ] && end=$(epoch "$2") && [ -n "$end" ] || { echo unknown; return; }
  echo "+$((end - $1))s"
}
yaml_value() { sed -n "s/^$2: *//p" "$1" | head -n 1 | tr -d '"'; }

# Newest running Pod of a model server.
server_pod() {
  k -n "$INFER_NS" get pods -l app.kubernetes.io/instance="$1" \
    --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1:].metadata.name}' 2>/dev/null
}

# Usage: wait_ready <namespace> <pod>
wait_ready() {
  k -n "$1" wait --for=condition=Ready "pod/$2" --timeout=180s >/dev/null 2>&1 || {
    echo "pod $2 not Ready:"
    k -n "$1" get pod "$2" -o jsonpath='{.status.conditions[?(@.status=="False")].message}{"\n"}'
    k -n "$1" get events --field-selector involvedObject.name="$2" -o jsonpath='{range .items[*]}{.message}{"\n"}{end}' | tail -n 3
    return 1
  }
}

# Usage: test_pod <namespace> <name> <service> <image> <python> [runAsUser]
# A Pod that satisfies every admission policy and idles until the checks exec into it.
test_pod() {
  local user=""
  [ -n "${6:-}" ] && user="runAsUser: $6"
  k apply -f - >/dev/null <<EOF || return 1
apiVersion: v1
kind: Pod
metadata:
  name: $2
  namespace: $1
  labels:
    project: $(yaml_value "$LLM_VALUES" project)
    environment: staging
    service: $3
    owner: $(yaml_value "$LLM_VALUES" owner)
    inference-check: $RUN
spec:
  serviceAccountName: staging-$3
  automountServiceAccountToken: false
  enableServiceLinks: false
  restartPolicy: Never
  securityContext:
    runAsNonRoot: true
    $user
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: check
      image: $4
      command: ["$5", "-c", "import time; time.sleep(1800)"]
      env:
        - name: PYTHONDONTWRITEBYTECODE
          value: "1"
      resources:
        requests: {cpu: 100m, memory: 128Mi}
        limits: {cpu: 200m, memory: 256Mi}
      securityContext:
        allowPrivilegeEscalation: false
        privileged: false
        readOnlyRootFilesystem: true
        capabilities:
          drop: [ALL]
EOF
  wait_ready "$1" "$2"
}

# --- Cold-start timings ------------------------------------------------------

# Usage: cold_start <release> <server container>
cold_start() {
  local pod t0 node node_created node_ready pulls init_log
  pod=$(server_pod "$1")
  [ -n "$pod" ] || { echo "no Pod for $1"; return; }
  t0=$(epoch "$(k -n "$INFER_NS" get pod "$pod" -o jsonpath='{.metadata.creationTimestamp}')")
  pt() { k -n "$INFER_NS" get pod "$pod" -o jsonpath="$1"; }
  node=$(pt '{.spec.nodeName}')
  node_created=$(k get node "$node" -o jsonpath='{.metadata.creationTimestamp}')
  node_ready=$(k get node "$node" -o jsonpath='{.status.conditions[?(@.type=="Ready")].lastTransitionTime}')
  echo "pod               $pod, created $(pt '{.metadata.creationTimestamp}')"
  if [ "$(epoch "$node_created")" -ge "$t0" ] 2>/dev/null; then
    echo "node created      $(since "$t0" "$node_created") ($node)"
    echo "node ready        $(since "$t0" "$node_ready")"
  else
    echo "node              existing node $node"
  fi
  echo "scheduled         $(since "$t0" "$(pt '{.status.conditions[?(@.type=="PodScheduled")].lastTransitionTime}')")"
  pulls=$(k -n "$INFER_NS" get events --field-selector involvedObject.name="$pod",reason=Pulled \
    -o jsonpath='{range .items[*]}{.message}{"\n"}{end}' 2>/dev/null \
    | sed -n 's|.*image "[^"]*/\([^/@"]*\)@[^"]*"\(.*\)|\1\2|p' | sed 's/ (.*//; s/\. Image size.*//')
  echo "image pulls       ${pulls:-not available (events expired)}" | sed '2,$s/^/                  /'
  init_log=$(k -n "$INFER_NS" logs "$pod" -c fetch-model 2>/dev/null | grep '"event": "verified"')
  echo "download          $(echo "$init_log" | sed -n 's/.*"download_seconds": \([0-9.]*\).*/\1s/p'), checksum $(echo "$init_log" | sed -n 's/.*"checksum_seconds": \([0-9.]*\).*/\1s/p')"
  echo "init finished     $(since "$t0" "$(pt '{.status.initContainerStatuses[0].state.terminated.finishedAt}')")"
  echo "server started    $(since "$t0" "$(pt "{.status.containerStatuses[?(@.name==\"$2\")].state.running.startedAt}")")"
  echo "model loaded      $(since "$t0" "$(k -n "$INFER_NS" logs "$pod" -c "$2" --timestamps 2>/dev/null \
    | grep -m 1 -E 'model loaded|"Ready"' | cut -d ' ' -f 1)")"
  echo "ready             $(since "$t0" "$(pt '{.status.conditions[?(@.type=="Ready")].lastTransitionTime}')")"
  echo "restarts          $(pt "{.status.containerStatuses[?(@.name==\"$2\")].restartCount}")"
}
llm_cold_start() { cold_start staging-llm-cpu llm-cpu; }
embeddings_cold_start() { cold_start staging-embeddings embeddings; }

# --- Admission -----------------------------------------------------------------

# Usage: running_matches_git <service>. The Application is Synced/Healthy and
# the server's running digest equals values-staging.yaml at the synced commit.
running_matches_git() {
  local state revision expected running
  state=$(k -n argocd get applications.argoproj.io "staging-$1" \
    -o jsonpath='{.status.sync.status}/{.status.health.status}')
  revision=$(k -n argocd get applications.argoproj.io "staging-$1" -o jsonpath='{.status.sync.revision}')
  git fetch --quiet origin main || true
  expected=$(git show "$revision:platform/services/$1/values-staging.yaml" 2>/dev/null \
    | sed -n 's/^ *digest: "\(sha256:[0-9a-f]*\)".*/\1/p')
  running=$(k -n "$INFER_NS" get pods -l app.kubernetes.io/instance="staging-$1" \
    -o jsonpath="{range .items[*]}{.status.containerStatuses[?(@.name==\"$1\")].imageID}{\"\n\"}{end}" \
    | sed -n 's/.*@\(sha256:[0-9a-f]*\)$/\1/p' | sort -u)
  echo "staging-$1 $state, revision ${revision:0:7}, expected ${expected:-unknown}, running ${running:-none}"
  [ "$state" = Synced/Healthy ] && [ -n "$expected" ] && [ "$running" = "$expected" ]
}
servers_admitted() { running_matches_git llm-cpu && running_matches_git embeddings; }

# Usage: fixture <name>. Prints one Deployment from the policy fixtures.
fixture() {
  awk -v name="$1" '
    /^---$/ { if (found) exit; doc = ""; next }
    { doc = doc $0 "\n" }
    $0 == "  name: " name { found = 1 }
    END { if (found) printf "%s", doc }
  ' "$FIXTURES"
}
# Usage: expected_failures <name>. Policies the CLI tests expect the fixture to fail.
expected_failures() {
  awk -v name="$1" '
    /- policy:/ { policy = $3 }
    /resources:/ { gsub(/[][,]/, " "); hit = (" " $0 " ") ~ (" " name " ") }
    /result: fail/ && hit { print policy }
  ' "$EXPECTED"
}

broken_fixtures_denied() {
  local name output policy rc=0
  for name in llm-cpu-no-provenance llm-cpu-no-bounds inference-breaks-all; do
    output=$(fixture "$name" | k create --dry-run=server -f - 2>&1)
    if ! echo "$output" | grep -q 'denied the request'; then
      echo "$name: admitted"; rc=1; continue
    fi
    for policy in $(expected_failures "$name"); do
      echo "$output" | grep -qF "$policy" || { echo "$name: denied, but not by $policy"; rc=1; }
    done
    echo "$name: denied by $(expected_failures "$name" | tr '\n' ' ')"
  done
  return $rc
}

# --- Callers -------------------------------------------------------------------

debug_pod() {
  local image
  image=$(k -n staging get deployment "$API_APP" -o jsonpath='{.spec.template.spec.containers[0].image}')
  k -n staging create serviceaccount "$DEBUG_SA" >/dev/null 2>&1 || true
  test_pod staging "$RUN-debug" debug "$image" python
}

allowed_caller_served() {
  debug_pod || return 1
  k -n staging exec "$RUN-debug" -- python -c '
import json, sys, urllib.request
url = sys.argv[1]
def post(path, body):
    request = urllib.request.Request(url + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(request, timeout=120))
chat = post("/v1/chat/completions", {"model": "assistant-chat", "max_tokens": 32,
    "messages": [{"role": "user", "content": "Name one planet."}]})
print("chat:", repr(chat["choices"][0]["message"]["content"][:60]), chat["usage"])
tokens = post("/tokenize", {"content": "Hello from the staging namespace."})["tokens"]
print("tokenize:", len(tokens), "tokens")
assert chat["choices"][0]["message"]["content"] and tokens' "http://$LLM_HOST:8080"
}

service_time() {
  local parallel
  parallel=$(k -n "$INFER_NS" get deployment staging-llm-cpu \
    -o jsonpath='{.spec.template.spec.containers[0].args}' | tr -d '[]"' | tr ',' '\n' \
    | awk 'prev == "--parallel" { print; exit } { prev = $0 }')
  k -n staging exec "$RUN-debug" -- python -c '
import json, statistics, sys, time, urllib.request
url, parallel, deadline = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
def post(path, body):
    request = urllib.request.Request(url + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(request, timeout=300))
sentence = "The platform team reviews each change to the cluster before it is applied. "
size = len(post("/tokenize", {"content": sentence * 100})["tokens"])
context = sentence * round(100 * 2000 / size)
prompt_tokens = len(post("/tokenize", {"content": context})["tokens"])
print(f"prompt about {prompt_tokens} tokens, max_tokens 384, ignore_eos")
times = []
for run in range(3):
    # A unique first line and cache_prompt false stop llama.cpp reusing the previous prompt.
    body = {"model": "assistant-chat", "max_tokens": 384, "ignore_eos": True, "cache_prompt": False,
        "messages": [{"role": "user", "content": f"Request {time.time_ns()}.\n{context}\nSummarise the text above."}]}
    begin = time.monotonic()
    result = post("/v1/chat/completions", body)
    seconds = time.monotonic() - begin
    times.append(seconds)
    t = result.get("timings", {})
    prompt_n, prompt_s = t.get("prompt_n"), t.get("prompt_ms", 0) / 1000
    predicted_n, predicted_s = t.get("predicted_n"), t.get("predicted_ms", 0) / 1000
    print(f"run {run + 1}: {seconds:.1f}s, prompt {prompt_n} tokens in {prompt_s:.1f}s, "
          f"generated {predicted_n} tokens in {predicted_s:.1f}s")
s = statistics.median(times)
print(f"service time S {s:.1f}s (median), parallel {parallel}")
if s >= deadline:
    print(f"S reaches the {deadline}s deadline: no queue fits in front of a request")
else:
    print(f"admission cap {parallel} x ({deadline} - {s:.1f}) / {s:.1f} = {int(parallel * (deadline - s) / s)} requests per replica")
' "http://$LLM_HOST:8080" "${parallel:-0}" "$DEADLINE_SECONDS"
}

# Usage: refused <host> <port>, run inside a test Pod's Python.
REFUSED='
import socket, sys
try:
    socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=5)
except OSError as error:
    print(sys.argv[1], "blocked", type(error).__name__)
else:
    sys.exit(sys.argv[1] + " reachable")'

debug_refused_by_embeddings() {
  k -n staging exec "$RUN-debug" -- python -c "$REFUSED" "$EMBED_HOST" 8080
}

unlisted_namespace_refused() {
  local image
  image=$(k -n staging get deployment "$API_APP" -o jsonpath='{.spec.template.spec.containers[0].image}')
  k create namespace "$CHECK_NS" >/dev/null || return 1
  k -n "$CHECK_NS" run net-check --image="$image" --restart=Never --labels="inference-check=$RUN" \
    --command -- python -c "$REFUSED
socket.create_connection((\"www.google.com\", 443), timeout=5).close()
print(\"internet connected\")" "$LLM_HOST" 8080 >/dev/null || return 1
  k -n "$CHECK_NS" wait --for=jsonpath='{.status.phase}'=Succeeded pod/net-check --timeout=120s >/dev/null
  local rc=$?
  k -n "$CHECK_NS" logs net-check
  return $rc
}

# --- Workload Identity -----------------------------------------------------------

identity_grants() {
  local image project bucket prefix model file size secret
  image=$(k -n "$INFER_NS" get deployment staging-llm-cpu -o jsonpath='{.spec.template.spec.initContainers[0].image}')
  project=$(yaml_value "$LLM_VALUES" project)
  bucket=$(yaml_value "$LLM_VALUES" '  bucket')
  prefix=$(yaml_value "$LLM_VALUES" '  bucketPath')
  model=$(yaml_value "$LLM_VALUES" '  name')
  file=$(yaml_value "models/$model.yaml" '  - path')
  size=$(yaml_value "models/$model.yaml" '    sizeBytes')
  secret=$(sed -n '/^secrets:/,/^[a-z]/s/^ *- name: *//p' "$API_VALUES" | head -n 1)
  test_pod "$INFER_NS" "$RUN-identity" llm-cpu "$image" /usr/bin/python3.13 10001 || return 1
  k -n "$INFER_NS" exec "$RUN-identity" -- /usr/bin/python3.13 -c '
import json, sys, urllib.error, urllib.parse, urllib.request
project, bucket, name, size, secret = sys.argv[1:6]
metadata = "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/"
def get(url, headers):
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=15).read()
flavor = {"Metadata-Flavor": "Google"}
print("identity", get(metadata + "email", flavor).decode())
auth = {"Authorization": "Bearer " + json.loads(get(metadata + "token", flavor))["access_token"]}
found = json.loads(get(f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/{urllib.parse.quote(name, safe=str())}", auth))
print("models bucket read, size", found["size"], "expected", size)
try:
    get(f"https://secretmanager.googleapis.com/v1/projects/{project}/secrets/{secret}/versions/latest:access", auth)
    sys.exit("secret read allowed")
except urllib.error.HTTPError as error:
    print("secret read refused, HTTP", error.code)
    assert error.code == 403
assert found["size"] == size' "$project" "$bucket" "$prefix$file" "$size" "$secret"
}

# --- Scaling metric --------------------------------------------------------------

metric_reaches_hpa() {
  local pod path deadline values active
  pod=$(server_pod staging-llm-cpu)
  path="/apis/custom.metrics.k8s.io/v1beta2/namespaces/$INFER_NS/pods/*/$(echo "$METRIC" | sed 's/|/%7C/g')"
  deadline=$(( $(date +%s) + 300 ))
  while :; do
    values=$(k get --raw "$path" 2>/dev/null | tr '{' '\n' | sed -n "s/.*\"name\":\"\($pod\)\".*/\1/p" | head -n 1)
    active=$(k -n "$INFER_NS" get hpa staging-llm-cpu \
      -o jsonpath='{.status.conditions[?(@.type=="ScalingActive")].status}' 2>/dev/null)
    if [ -n "$values" ] && [ "$active" = True ]; then break; fi
    [ "$(date +%s)" -ge "$deadline" ] && break
    sleep 15
  done
  echo "metric for $pod: ${values:+returned}${values:-missing}, ScalingActive: ${active:-unknown}"
  k -n "$INFER_NS" get hpa staging-llm-cpu -o jsonpath='{range .status.conditions[*]}{.type}={.status} {.reason}{"\n"}{end}'
  [ -n "$values" ] && [ "$active" = True ]
}

echo "Inference checks, $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "  Local HEAD:  $(git rev-parse --short HEAD)"
echo "  Nodes:       $(k get nodes -L cloud.google.com/gke-nodepool --no-headers | awk '{print $NF}' | sort | uniq -c | awk '{printf "%s x%s  ", $2, $1}')"
echo

record "llm-cpu cold start" llm_cold_start
record "embeddings cold start" embeddings_cold_start
check "model servers Synced, Healthy and running the digests in Git" servers_admitted
check "admission denies the broken inference fixtures" broken_fixtures_denied
check "debug caller in staging gets a chat completion and tokens" allowed_caller_served
record "service time and admission cap" service_time
check "debug caller cannot reach embeddings" debug_refused_by_embeddings
check "a Pod in an unlisted namespace cannot reach llm-cpu" unlisted_namespace_refused
check "llm-cpu identity reads the models bucket and is refused the secret" identity_grants
check "the scaling metric reaches the HPA" metric_reaches_hpa

echo
echo "$passed passed, $failed failed"
[ "$failed" -eq 0 ]
