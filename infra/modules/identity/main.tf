resource "google_service_account" "nodes" {
  project         = var.project_id
  account_id      = "${var.environment}-nodes-sa"
  display_name    = "GKE nodes (${var.environment})"
  deletion_policy = "PREVENT"
}

resource "google_project_iam_member" "nodes_default_role" {
  project = var.project_id
  role    = "roles/container.defaultNodeServiceAccount"
  member  = google_service_account.nodes.member
}

resource "google_service_account" "build_validate" {
  project         = var.project_id
  account_id      = "${var.environment}-build-validate-sa"
  display_name    = "Cloud Build PR Validation ${var.environment}"
  deletion_policy = "PREVENT"
}

resource "google_service_account" "build_publish" {
  project         = var.project_id
  account_id      = "${var.environment}-build-publish-sa"
  display_name    = "Cloud Build publishing ${var.environment}"
  deletion_policy = "PREVENT"
}

resource "google_project_iam_member" "log_writer" {
  for_each = {
    build_validate = google_service_account.build_validate.member
    build_publish  = google_service_account.build_publish.member
  }

  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = each.value
}
