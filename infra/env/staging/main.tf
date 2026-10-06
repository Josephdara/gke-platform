module "foundation" {
  source = "../../modules/foundation"

  project_id  = var.project_id
  region      = var.region
  environment = var.environment
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

resource "google_artifact_registry_repository_iam_member" "nodes_read_mirror" {
  project    = var.project_id
  location   = var.region
  repository = module.foundation.mirror_repository_id
  role       = "roles/artifactregistry.reader"
  member     = module.identity.node_service_account_member
}

resource "google_artifact_registry_repository_iam_member" "ci_write_images" {
  project    = var.project_id
  location   = var.region
  repository = module.foundation.images_repository_id
  role       = "roles/artifactregistry.writer"
  member     = module.identity.ci_build_publish_member

}

module "secrets" {
  source = "../../modules/secrets"

  project_id  = var.project_id
  environment = var.environment
  service_secrets = {
    platform-verification-api = ["demo"]
  }
  ungranted_secrets = ["forbidden-demo"]
}

module "pipeline" {
  source = "../../modules/pipeline"

  project_id                  = var.project_id
  region                      = var.region
  environment                 = var.environment
  name_prefix                 = local.prefix
  connection_id               = "projects/${var.project_id}/locations/${var.region}/connections/${var.environment}-github"
  repository_uri              = "https://github.com/Josephdara/gke-platform.git"
  validate_service_account_id = module.identity.ci_build_validate_id
  publish_service_account_id  = module.identity.ci_build_publish_id
  images_repository_id        = module.foundation.images_repository_id
  labels                      = { component = "pipeline" }
}

resource "google_storage_bucket_iam_member" "ci_write_evidence" {
  for_each = toset([
    "roles/storage.objectCreator",
    "roles/storage.legacyBucketReader"
  ])
  bucket = module.pipeline.evidence_bucket_name
  role   = each.value
  member = module.identity.ci_build_publish_member
}

module "edge" {
  source = "../../modules/edge"

  project_id  = var.project_id
  environment = var.environment
  dns_name    = "gke.josephdara.com"
  lab_enabled = var.lab_enabled

  depends_on = [module.foundation]
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
