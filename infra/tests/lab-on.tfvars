# Test input for infra/tests/validate-terraform.sh only. Terraform never loads
# this file on its own; the script passes it to Trivy so the resources behind
# the lab_enabled toggle are scanned.
lab_enabled = true
