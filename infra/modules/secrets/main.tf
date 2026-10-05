data "google_project" "this" {
  project_id = var.project_id
}

locals {
  owned = merge([
    for service, names in var.service_secrets : {
      for name in names : "${var.environment}-${service}-${name}" => service
    }
  ]...)
  workload_pool = "projects/${data.google_project.this.number}/locations/global/workloadIdentityPools/${var.project_id}.svc.id.goog"
}

resource "google_secret_manager_secret" "this" {
  for_each = merge(local.owned, { for name in var.ungranted_secrets : "${var.environment}-${name}" => null })

  project         = var.project_id
  secret_id       = each.key
  labels          = each.value == null ? {} : { service = each.value }
  deletion_policy = "PREVENT"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_iam_member" "accessor" {
  for_each = local.owned

  project   = var.project_id
  secret_id = google_secret_manager_secret.this[each.key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "principal://iam.googleapis.com/${local.workload_pool}/subject/ns/${var.environment}/sa/${var.environment}-${each.value}"
}

resource "google_project_iam_audit_config" "secret_manager" {
  project = var.project_id
  service = "secretmanager.googleapis.com"

  audit_log_config {
    log_type = "DATA_READ"
  }
}
