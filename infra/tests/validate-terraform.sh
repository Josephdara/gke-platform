#!/usr/bin/env bash
# Validates the Terraform configuration under infra/: formatting, the no-tfvars
# rule, the committed provider lock file, configuration validity with the lab
# on and off, and Trivy misconfiguration checks. Needs no cloud credentials.
# Usage: infra/tests/validate-terraform.sh
# Exit codes: 0 all checks passed, 1 a check failed, 2 setup problem.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

ROOT=infra/env/staging
LAB_ON_VARS=infra/tests/lab-on.tfvars
TRIVY_IGNORE=infra/.trivyignore.yaml

for tool in terraform trivy; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    case $tool in
      terraform) hint="brew install hashicorp/tap/terraform" ;;
      *) hint="brew install $tool" ;;
    esac
    echo "Missing $tool. Install it with: $hint" >&2
    exit 2
  fi
done

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

echo "$(terraform version | head -n 1), trivy $(trivy --version | awk 'NR==1 {print $2}')"
echo

# Formatting: terraform fmt must have nothing to change.
if terraform fmt -check -recursive infra > "$WORK/fmt.log" 2>&1; then
  pass "format"
else
  fail "format: run terraform fmt on these files" "$WORK/fmt.log"
fi

# No tfvars: every run must use committed values only.
find infra -name .terraform -prune -o \
  \( -name terraform.tfvars -o -name '*.auto.tfvars' \) -print > "$WORK/tfvars.log"
if [ ! -s "$WORK/tfvars.log" ]; then
  pass "no terraform.tfvars or *.auto.tfvars"
else
  fail "tfvars files found; move their values into committed configuration" "$WORK/tfvars.log"
fi

# Init without the backend, so no credentials are needed. A read-only lock file
# makes init fail instead of changing the committed provider selections.
if terraform -chdir="$ROOT" init -backend=false -input=false -lockfile=readonly -no-color \
  > "$WORK/init.log" 2>&1; then
  pass "init (no backend, read-only lock file)"
else
  fail "init (no backend, read-only lock file)" "$WORK/init.log"
fi

# Validate both shapes of the configuration.
for lab in false true; do
  if terraform -chdir="$ROOT" validate -no-color -var="lab_enabled=$lab" \
    > "$WORK/validate-$lab.log" 2>&1; then
    pass "validate (lab_enabled=$lab)"
  else
    fail "validate (lab_enabled=$lab)" "$WORK/validate-$lab.log"
  fi
done

# Trivy misconfiguration scan. The lab-on variables make Trivy evaluate the
# resources behind the lab_enabled toggle, which the default would skip.
if trivy config --quiet \
  --misconfig-scanners terraform \
  --severity HIGH,CRITICAL \
  --exit-code 1 \
  --ignorefile "$TRIVY_IGNORE" \
  --skip-dirs infra/private \
  --skip-dirs '**/.terraform' \
  --tf-vars "$LAB_ON_VARS" \
  infra > "$WORK/trivy.log" 2>&1; then
  pass "trivy (HIGH, CRITICAL)"
else
  fail "trivy (HIGH, CRITICAL)" "$WORK/trivy.log"
fi

echo
echo "$passed passed, $failed failed"
[ "$failed" -eq 0 ]
