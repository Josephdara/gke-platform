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

module "network" {
  source = "../../modules/network"
  count  = var.lab_enabled ? 1 : 0

  project_id  = var.project_id
  environment = var.environment
  region      = var.region
}

module "gke" {
  source = "../../modules/gke"
  count  = var.lab_enabled ? 1 : 0

  project_id                 = var.project_id
  environment                = var.environment
  zone                       = var.zone
  network_id                 = module.network[0].network_id
  subnet_id                  = module.network[0].subnetwork_id
  pods_range_id              = module.network[0].pods_range_name
  services_range_id          = module.network[0].services_range_name
  node_service_account_email = module.identity.node_service_account_email
  labels                     = { component = "gke" }
}
