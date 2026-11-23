#!/usr/bin/env bash
# Records a served model in the Vertex AI Model Registry, as an inventory entry: where its files
# are in the models bucket, the serving image by digest, and provenance labels. Nothing is deployed
# to a Vertex AI endpoint, so Vertex never reads the files and needs no access to the bucket. Each new model revision or serving image becomes a new version, and the
# `staging` alias moves to the version staging runs. Run it with your own credentials after a
# release; a version that is already registered is left as it is.
# Usage: models/register-model.sh models/<name>.yaml platform/services/<service>/values-staging.yaml [PROMPT_VERSION]
# Settings: PROJECT_ID, ENVIRONMENT, REGION (defaults gke-build-proj, staging, us-east4), and
#   DRY_RUN=1 to print the commands instead of running them.
# Exit codes: 0 registered or already current, 1 a command failed, 2 setup problem.
set -euo pipefail

MANIFEST=${1:-}
VALUES=${2:-}
PROMPT=${3:-}
[ -f "$MANIFEST" ] && [ -f "$VALUES" ] || {
  echo "Usage: $0 models/<name>.yaml platform/services/<service>/values-staging.yaml [PROMPT_VERSION]" >&2; exit 2; }
for tool in gcloud curl python3; do
  command -v "$tool" >/dev/null 2>&1 || { echo "Missing $tool" >&2; exit 2; }
done

# gcloud must never stop to ask, for example to enable an API.
export CLOUDSDK_CORE_DISABLE_PROMPTS=1
PROJECT_ID=${PROJECT_ID:-gke-build-proj}
ENVIRONMENT=${ENVIRONMENT:-staging}
REGION=${REGION:-us-east4}
ALIAS=staging

field() { awk -v k="$1:" '$1 == k { print $2; exit }' "$2"; }
name=$(field name "$MANIFEST")
revision=$(field sourceRevision "$MANIFEST")
format=$(field format "$MANIFEST")
quantization=$(field quantization "$MANIFEST")
prefix=$(field bucketPath "$MANIFEST")
sha=$(awk '$1 == "sha256:" { print $2; exit }' "$MANIFEST")
repository=$(field repository "$VALUES")
digest=$(field digest "$VALUES" | tr -d '"')
[ -n "$name" ] && [ -n "$revision" ] && [ -n "$repository" ] && [ -n "$digest" ] || {
  echo "Missing name or sourceRevision in $MANIFEST, or image repository or digest in $VALUES" >&2; exit 2; }

# The chat model answers on llama.cpp's OpenAI route; the embeddings model on TEI's /embed.
if [ "$format" = gguf ]; then predict=/v1/chat/completions; else predict=/embed; fi
display="$ENVIRONMENT-$name"
# Label values allow lowercase letters, digits, - and _, up to 63 characters.
clean() { printf '%s' "$1" | tr 'A-Z.' 'a-z-' | tr -cd 'a-z0-9_-' | cut -c1-63; }
image_id=$(printf '%s' "${digest#sha256:}" | cut -c1-16)
labels="environment=$ENVIRONMENT,served-on=gke,model=$(clean "$name"),revision=$(clean "$revision")"
labels="$labels,sha256=$(printf '%s' "$sha" | cut -c1-16),image=$image_id,files=models-bucket"
files="gs://$PROJECT_ID-$ENVIRONMENT-models/$prefix"
[ -n "$quantization" ] && labels="$labels,quantization=$(clean "$quantization")"
[ -n "$PROMPT" ] && labels="$labels,prompt-version=$(clean "$PROMPT")"

run() { if [ "${DRY_RUN:-}" = 1 ]; then printf 'DRY RUN:'; printf ' %q' "$@"; echo; else "$@"; fi; }
api="https://$REGION-aiplatform.googleapis.com/v1"
aliases() {  # model@version, then aliases such as staging or -staging to remove one
  local body
  body=$(python3 -c 'import json, sys; print(json.dumps({"versionAliases": sys.argv[1:]}))' "${@:2}")
  run curl -sS --fail-with-body -X POST "$api/$1:mergeVersionAliases" \
    -H "Authorization: Bearer $(gcloud auth print-access-token)" -H "Content-Type: application/json" -d "$body"
}

if ! listing=$(gcloud ai models list --project="$PROJECT_ID" --region="$REGION" \
  --filter="displayName=$display" --format="value(name)" 2>&1); then
  echo "Could not list models in $REGION: is the Vertex AI API enabled, and is the region supported?" >&2
  printf '%s\n' "$listing" | tail -2 >&2
  exit 1
fi
# gcloud prints each model's ID; the API calls below need its full name.
id=$(printf '%s\n' "$listing" | grep -E '^[0-9]+$' | head -1 || true)
model=${id:+projects/$PROJECT_ID/locations/$REGION/models/$id}
upload=(gcloud ai models upload --project="$PROJECT_ID" --region="$REGION" --display-name="$display"
  --container-image-uri="$repository@$digest" --container-ports=8080 --container-health-route=/health
  --container-predict-route="$predict" --labels="$labels"
  --description="Served on GKE in $ENVIRONMENT from $repository@$digest. Model files: $files. An inventory entry, not deployed")

if [ -z "$model" ]; then
  echo "Registering $display"
  run "${upload[@]}" --version-aliases="$ALIAS"
  exit 0
fi

# One version per model revision and serving image.
versions=$(gcloud ai models list-version "$model" --project="$PROJECT_ID" --region="$REGION" --format=json)
current=$(printf '%s' "$versions" | python3 -c '
import json, sys
revision, image = sys.argv[1], sys.argv[2]
for v in json.load(sys.stdin):
    labels = v.get("labels", {})
    if labels.get("revision") == revision and labels.get("image") == image:
        print(v["versionId"]); break' "$(clean "$revision")" "$image_id")
staged=$(printf '%s' "$versions" | python3 -c '
import json, sys
print(next((v["versionId"] for v in json.load(sys.stdin) if "staging" in v.get("versionAliases", [])), ""))')

if [ -z "$current" ]; then
  echo "Adding a version of $display"
  run "${upload[@]}" --parent-model="$model"
  current=$(gcloud ai models list-version "$model" --project="$PROJECT_ID" --region="$REGION" \
    --sort-by=~versionCreateTime --limit=1 --format="value(versionId)")
fi
if [ "$staged" != "$current" ]; then
  [ -n "$staged" ] && aliases "$model@$staged" "-$ALIAS"
  aliases "$model@$current" "$ALIAS"
  echo "Moved $ALIAS to version $current of $display"
else
  echo "$display version $current is registered and already $ALIAS"
fi
