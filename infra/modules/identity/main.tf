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
