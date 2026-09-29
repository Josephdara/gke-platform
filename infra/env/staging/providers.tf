provider "google" {
  project        = var.project_id
  region         = var.region
  zone           = var.zone
  default_labels = local.common_labels
}
