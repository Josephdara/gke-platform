locals {
  repository = "${var.region}-docker.pkg.dev/${var.project_id}/${var.images_repository_id}"
  image      = "${local.repository}/platform-verification-api"
}

resource "google_storage_bucket" "evidence" {
  project                     = var.project_id
  name                        = "${var.name_prefix}-build-evidence"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = var.labels
  deletion_policy             = "PREVENT"

  lifecycle_rule {
    condition {
      age            = 90
      matches_prefix = var.evidence_expiring_prefixes
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_cloudbuildv2_repository" "this" {
  project           = var.project_id
  location          = var.region
  name              = trimsuffix(basename(var.repository_uri), ".git")
  parent_connection = var.connection_id
  remote_uri        = var.repository_uri
}

resource "google_cloudbuild_trigger" "validate" {
  project         = var.project_id
  location        = var.region
  name            = "${var.environment}-pr-validate"
  service_account = var.validate_service_account_id
  filename        = "pipeline/cloudbuild-validate.yaml"

  substitutions = {
    _IMAGE = local.image
  }

  repository_event_config {
    repository = google_cloudbuildv2_repository.this.id

    pull_request {
      branch          = "^main$"
      comment_control = "COMMENTS_ENABLED_FOR_EXTERNAL_CONTRIBUTORS_ONLY"
    }
  }
}

# One publish trigger per application. A merge publishes only the applications it changed;
# the API's trigger keeps its original name.
resource "google_cloudbuild_trigger" "publish" {
  for_each = toset(var.publish_apps)

  project         = var.project_id
  location        = var.region
  name            = each.key == "platform-verification-api" ? "${var.environment}-main-publish" : "${var.environment}-${each.key}-publish"
  service_account = var.publish_service_account_id
  filename        = "pipeline/cloudbuild-publish.yaml"

  included_files = [
    "apps/${each.key}/**",
    "pipeline/cloudbuild-publish.yaml",
  ]
  ignored_files = ["apps/${each.key}/**/*.md"]

  substitutions = {
    _APP             = each.key
    _IMAGE           = "${local.repository}/${each.key}"
    _EVIDENCE_BUCKET = google_storage_bucket.evidence.name
  }

  repository_event_config {
    repository = google_cloudbuildv2_repository.this.id

    push {
      branch = "^main$"
    }
  }
}
moved {
  from = google_cloudbuild_trigger.publish
  to   = google_cloudbuild_trigger.publish["platform-verification-api"]
}
