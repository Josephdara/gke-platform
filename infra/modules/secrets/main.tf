data "google_project" "this" {
  project_id = var.project_id
}

locals {
  secrets = {
    for name, readers in var.secret_readers : "${var.environment}-${name}" => readers[0].service
  }
  grants = merge([
    for name, readers in var.secret_readers : {
      for r in readers : "${var.environment}-${name}/${r.namespace}/${r.service}" => {
        secret_id = "${var.environment}-${name}"
        member    = "principal://iam.googleapis.com/${local.workload_pool}/subject/ns/${r.namespace}/sa/${var.environment}-${r.service}"
      }
    }
  ]...)
  workload_pool = "projects/${data.google_project.this.number}/locations/global/workloadIdentityPools/${var.project_id}.svc.id.goog"
}

resource "google_secret_manager_secret" "this" {
  for_each = merge(local.secrets, { for name in var.ungranted_secrets : "${var.environment}-${name}" => null })

  project         = var.project_id
  secret_id       = each.key
  labels          = each.value == null ? {} : { service = each.value }
  deletion_policy = "PREVENT"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_iam_member" "accessor" {
  for_each = local.grants

  project   = var.project_id
  secret_id = google_secret_manager_secret.this[each.value.secret_id].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = each.value.member
}

moved {
  from = google_secret_manager_secret_iam_member.accessor["staging-platform-verification-api-demo"]
  to   = google_secret_manager_secret_iam_member.accessor["staging-platform-verification-api-demo/staging/platform-verification-api"]
}

resource "google_project_iam_audit_config" "secret_manager" {
  project = var.project_id
  service = "secretmanager.googleapis.com"

  audit_log_config {
    log_type = "DATA_READ"
  }
}
