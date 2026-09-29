locals {
  common_labels = {
    project     = var.project_id
    environment = var.environment
    service     = var.service
    owner       = var.owner
  }
  prefix = "${var.project_id}-${var.environment}"
}