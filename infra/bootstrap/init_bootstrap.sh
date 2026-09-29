#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/infra.env"
LIFECYCLE_FILE="${SCRIPT_DIR}/state-lifecycle.json"

APPLY_CLEANUP=false
for arg in "$@"; do
  case "$arg" in
    --apply-cleanup) APPLY_CLEANUP=true ;;
    *) echo "Error: unknown argument '$arg'" >&2; exit 2 ;;
  esac
done

die() { echo "Error: $*" >&2; exit 1; }
step() { echo; echo "== $*"; }

# ------------------------------------------------------------------------------
# 1. Load and validate settings
# ------------------------------------------------------------------------------
[[ -f "$ENV_FILE" ]] || die "missing ${ENV_FILE}"
[[ -f "$LIFECYCLE_FILE" ]] || die "missing ${LIFECYCLE_FILE}"
command -v gcloud >/dev/null || { echo "Error: gcloud not found" >&2; exit 2; }

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

: "${PROJECT_ID:?PROJECT_ID missing in infra.env}"
: "${ENV:?ENV missing in infra.env}"
: "${REGION:?REGION missing in infra.env}"
: "${SERVICE:?SERVICE missing in infra.env}"
: "${OWNER:?OWNER missing in infra.env}"

# Label values: lowercase letters, digits, underscores, hyphens; 1 to 63 chars.
for pair in "project=${PROJECT_ID}" "environment=${ENV}" "service=${SERVICE}" "owner=${OWNER}"; do
  value="${pair#*=}"
  [[ "$value" =~ ^[a-z0-9_-]{1,63}$ ]] || die "invalid label value '${value}' for ${pair%%=*}"
done
LABELS="project=${PROJECT_ID},environment=${ENV},service=${SERVICE},owner=${OWNER},managed-by=bootstrap"

BUCKETS="${PROJECT_ID}-${ENV}-identity-tfstate ${PROJECT_ID}-${ENV}-tfstate"

# ------------------------------------------------------------------------------
# 2. Preconditions: identity, project, billing, ADC quota project
# ------------------------------------------------------------------------------
step "Preconditions"
ACCOUNT="$(gcloud config get-value account 2>/dev/null || true)"
[[ -n "$ACCOUNT" ]] || die "no active gcloud account; run gcloud auth login"
echo "Running as:  ${ACCOUNT}"

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')" \
  || die "cannot read project ${PROJECT_ID}"
echo "Project:     ${PROJECT_ID} (${PROJECT_NUMBER})"

BILLING_ENABLED="$(gcloud billing projects describe "$PROJECT_ID" --format='value(billingEnabled)')"
[[ "$BILLING_ENABLED" == "True" ]] || die "billing is not enabled on ${PROJECT_ID}"
echo "Billing:     enabled (check the currency in the console: Billing > Account management)"

ADC_FILE="${HOME}/.config/gcloud/application_default_credentials.json"
if [[ -f "$ADC_FILE" ]]; then
  ADC_QUOTA="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('quota_project_id',''))" "$ADC_FILE")"
  if [[ "$ADC_QUOTA" == "$PROJECT_ID" ]]; then
    echo "ADC:         quota project ${ADC_QUOTA}"
  else
    echo "Warning: ADC quota project is '${ADC_QUOTA:-unset}', expected '${PROJECT_ID}' "
  fi
else
  echo "Warning: no Application Default Credentials yet "
fi

# ------------------------------------------------------------------------------
# 3. Bootstrap APIs
# ------------------------------------------------------------------------------
step "Enabling bootstrap APIs"
gcloud services enable \
  serviceusage.googleapis.com \
  cloudresourcemanager.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  storage.googleapis.com \
  --project="$PROJECT_ID"


# ------------------------------------------------------------------------------
# 4. Compute Engine defaults (listed; deleted only with --apply-cleanup)
# ------------------------------------------------------------------------------
step "Compute Engine defaults"
COMPUTE_ENABLED="$(gcloud services list --enabled --project="$PROJECT_ID" \
  --filter='config.name=compute.googleapis.com' --format='value(config.name)')"

if [[ -z "$COMPUTE_ENABLED" ]]; then
  echo "Compute Engine API is off; nothing to clean."
else
  DEFAULT_NETWORK="$(gcloud compute networks list --project="$PROJECT_ID" \
    --filter='name=default' --format='value(name)')"

  if [[ -n "$DEFAULT_NETWORK" ]]; then
    RULES="$(gcloud compute firewall-rules list --project="$PROJECT_ID" \
      --filter='network ~ /global/networks/default$' --format='value(name)')"
    echo "Found network 'default' with firewall rules: ${RULES:+${RULES//$'\n'/ }}"
    if [[ "$APPLY_CLEANUP" == true ]]; then
      for rule in $RULES; do
        gcloud compute firewall-rules delete "$rule" --project="$PROJECT_ID" --quiet
      done
      gcloud compute networks delete default --project="$PROJECT_ID" --quiet
      echo "Deleted network 'default'."
    else
      echo "Not deleted. Rerun with --apply-cleanup to delete."
    fi
  else
    echo "No 'default' network."
  fi

  COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
  EDITOR_GRANT="$(gcloud projects get-iam-policy "$PROJECT_ID" \
    --flatten='bindings[].members' \
    --filter="bindings.role=roles/editor AND bindings.members=serviceAccount:${COMPUTE_SA}" \
    --format='value(bindings.members)')"

  if [[ -n "$EDITOR_GRANT" ]]; then
    echo "Compute default service account holds roles/editor."
    if [[ "$APPLY_CLEANUP" == true ]]; then
      gcloud projects remove-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:${COMPUTE_SA}" --role=roles/editor \
        --condition=None --quiet >/dev/null
      echo "Removed roles/editor."
    else
      echo "Not removed. Rerun with --apply-cleanup to remove."
    fi
  else
    echo "Compute default service account does not hold roles/editor."
  fi
fi

# ------------------------------------------------------------------------------
# 5. State buckets: create if missing, then always reapply every setting
# ------------------------------------------------------------------------------
# Returns 0 if the bucket exists in this project, 1 if the name is free.
# Stops on anything else (name owned elsewhere, auth errors).
bucket_exists() {
  local bucket="$1" out
  if out="$(gcloud storage buckets describe "gs://${bucket}" --format='value(name)' 2>&1)"; then
    gcloud storage ls --project="$PROJECT_ID" | grep -qx "gs://${bucket}/" \
      || die "gs://${bucket} exists but is not in project ${PROJECT_ID}"
    return 0
  fi
  if echo "$out" | grep -qiE '404|not found'; then
    return 1
  fi
  die "cannot check gs://${bucket}: ${out}"
}

for bucket in $BUCKETS; do
  step "State bucket gs://${bucket}"

  if bucket_exists "$bucket"; then
    echo "Exists; reapplying settings."
  else
    gcloud storage buckets create "gs://${bucket}" \
      --project="$PROJECT_ID" \
      --location="$REGION" \
      --default-storage-class=STANDARD \
      --uniform-bucket-level-access \
      --public-access-prevention \
      --soft-delete-duration=7d
  fi

  gcloud storage buckets update "gs://${bucket}" \
    --uniform-bucket-level-access \
    --public-access-prevention \
    --versioning \
    --soft-delete-duration=7d \
    --lifecycle-file="$LIFECYCLE_FILE" \
    --update-labels="$LABELS"

  # Remove the automatic grants to project viewers and editors; keep owners.
  # get-iam-policy has no --filter, so fetch every role,member row and grep.
  POLICY="$(gcloud storage buckets get-iam-policy "gs://${bucket}" \
    --flatten='bindings[].members' \
    --format='csv[no-heading](bindings.role,bindings.members)')"
  GRANTS="$(echo "$POLICY" | grep -E ',project(Viewer|Editor):' || true)"

  if [[ -n "$GRANTS" ]]; then
    while IFS=, read -r role member; do
      echo "Removing ${role} from ${member}"
      gcloud storage buckets remove-iam-policy-binding "gs://${bucket}" \
        --member="$member" --role="$role" </dev/null >/dev/null
    done <<< "$GRANTS"
  else
    echo "No viewer or editor grants to remove."
  fi
done

# ------------------------------------------------------------------------------
# 6. Verification output 
# ------------------------------------------------------------------------------
step "Verification"
gcloud projects describe "$PROJECT_ID" --format='yaml(projectId,projectNumber,labels)'
for bucket in $BUCKETS; do
  echo "--- gs://${bucket}"
  gcloud storage buckets describe "gs://${bucket}"
  gcloud storage buckets get-iam-policy "gs://${bucket}" --format='yaml(bindings)'
done

echo
echo "Bootstrap complete for ${PROJECT_ID}. Cleanup applied: ${APPLY_CLEANUP}."
