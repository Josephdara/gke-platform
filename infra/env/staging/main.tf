module "foundation" {
  source = "../../modules/foundation"

  project_id  = var.project_id
  region      = var.region
  name_prefix = local.prefix
  labels      = { component = "image-registry" }
}

module "identity" {
  source = "../../modules/identity"

  project_id  = var.project_id
  environment = var.environment
}

resource "google_artifact_registry_repository_iam_member" "nodes_read_images" {
  project    = var.project_id
  location   = var.region
  repository = module.foundation.images_repository_id
  role       = "roles/artifactregistry.reader"
  member     = module.identity.node_service_account_member
}
