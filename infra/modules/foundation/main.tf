locals {
  services = toset([
    "artifactregistry.googleapis.com",
    "compute.googleapis.com",
    "container.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "secretmanager.googleapis.com",
  ])
}

resource "google_project_service" "this" {
  for_each = local.services

  project                    = var.project_id
  service                    = each.value
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_artifact_registry_repository" "images" {
  project                = var.project_id
  location               = var.region
  repository_id          = "${var.name_prefix}-images"
  format                 = "DOCKER"
  description            = "Container images for platform services"
  labels                 = var.labels
  deletion_policy        = "PREVENT"
  cleanup_policy_dry_run = true

  docker_config {
    immutable_tags = true
  }

  vulnerability_scanning_config {
    enablement_config = "DISABLED"
  }

  cleanup_policies {
    id     = "keep-recent-versions"
    action = "KEEP"
    most_recent_versions {
      keep_count = 5
    }
  }

  cleanup_policies {
    id     = "delete-older-than-7-days"
    action = "DELETE"
    condition {
      tag_state  = "ANY"
      older_than = "604800s"
    }
  }

  depends_on = [google_project_service.this]
}
