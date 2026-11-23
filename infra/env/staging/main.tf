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
  secret_readers = {
    platform-verification-api-demo = [
      { namespace = var.environment, service = "platform-verification-api" }
    ]
    # pgvector's superuser creates the two application roles at first start; nothing else uses it.
    pgvector-admin = [
      { namespace = "${var.environment}-inference", service = "pgvector" }
    ]
    # ingest owns the schema and the corpus tables.
    pgvector-ingest = [
      { namespace = "${var.environment}-inference", service = "pgvector" },
      { namespace = "${var.environment}-inference", service = "ingest" }
    ]
    # rag-api's accounts, as scrypt hashes, and the key that signs its session cookies.
    rag-api-users = [
      { namespace = var.environment, service = "rag-api" }
    ]
    rag-api-session-key = [
      { namespace = var.environment, service = "rag-api" }
    ]
    # rag-api reads the corpus and writes only its own conversations.
    pgvector-rag-api = [
      { namespace = "${var.environment}-inference", service = "pgvector" },
      { namespace = var.environment, service = "rag-api" }
    ]
    # The password of the rag-api account exempt from the rate limit, which loadgen signs in as.
    rag-api-bench-password = [
      { namespace = var.environment, service = "loadgen" }
    ]
  }
  ungranted_secrets = ["forbidden-demo"]
}

locals {
  storage_readers = {
    models = [
      { namespace = "${var.environment}-inference", service = "llm-cpu" },
      { namespace = "${var.environment}-inference", service = "embeddings" }
    ]
  }
  storage_grants = merge([
    for bucket, readers in local.storage_readers : {
      for r in readers : "${bucket}/${r.namespace}/${r.service}" => {
        bucket = bucket
        member = "principal://iam.googleapis.com/${module.secrets.workload_pool}/subject/ns/${r.namespace}/sa/${var.environment}-${r.service}"
      }
    }
  ]...)
  buckets = {
    models   = module.foundation.models_bucket_name
    evidence = module.pipeline.evidence_bucket_name
  }
  # Object access limited to one prefix by an IAM condition on the object name. The readers
  # fetch known object paths and never list, so a bucket-level list permission is not needed.
  prefix_grants = {
    "models/corpus/ingest" = {
      bucket    = "models"
      prefix    = "corpus/"
      role      = "roles/storage.objectViewer"
      namespace = "${var.environment}-inference"
      service   = "ingest"
    }
    "evidence/inference/ingest/ingest" = {
      bucket    = "evidence"
      prefix    = "inference/ingest/"
      role      = "roles/storage.objectCreator"
      namespace = "${var.environment}-inference"
      service   = "ingest"
    }
    "evidence/inference/loadgen/loadgen" = {
      bucket    = "evidence"
      prefix    = "inference/loadgen/"
      role      = "roles/storage.objectCreator"
      namespace = var.environment
      service   = "loadgen"
    }
  }
}

# The Custom Metrics Stackdriver Adapter reads Managed Prometheus series for the HPA.
resource "google_project_iam_member" "metrics_adapter_viewer" {
  project = var.project_id
  role    = "roles/monitoring.viewer"
  member  = "principal://iam.googleapis.com/${module.secrets.workload_pool}/subject/ns/custom-metrics/sa/custom-metrics-stackdriver-adapter"
}

resource "google_storage_bucket_iam_member" "workload_read" {
  for_each = local.storage_grants

  bucket = local.buckets[each.value.bucket]
  role   = "roles/storage.objectViewer"
  member = each.value.member
}

resource "google_storage_bucket_iam_member" "workload_prefix" {
  for_each = local.prefix_grants

  bucket = local.buckets[each.value.bucket]
  role   = each.value.role
  member = "principal://iam.googleapis.com/${module.secrets.workload_pool}/subject/ns/${each.value.namespace}/sa/${var.environment}-${each.value.service}"

  condition {
    title       = "only-${trimsuffix(replace(each.value.prefix, "/", "-"), "-")}"
    description = "Objects under ${each.value.prefix} only"
    expression  = "resource.name.startsWith(\"projects/_/buckets/${local.buckets[each.value.bucket]}/objects/${each.value.prefix}\")"
  }
}

# Uploads also need the bucket's metadata, as the pipeline's evidence uploader does.
resource "google_storage_bucket_iam_member" "ingest_evidence_bucket_reader" {
  bucket = module.pipeline.evidence_bucket_name
  role   = "roles/storage.legacyBucketReader"
  member = "principal://iam.googleapis.com/${module.secrets.workload_pool}/subject/ns/${var.environment}-inference/sa/${var.environment}-ingest"
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
  publish_apps                = ["platform-verification-api", "rag-api", "ingest", "loadgen"]
  # Build evidence under these prefixes expires after 90 days; inference evidence is kept.
  evidence_expiring_prefixes = ["platform-verification-api/", "rag-api/", "ingest/", "loadgen/"]
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
  hosts       = ["api", "assistant"]
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
  inference_cpu_enabled      = var.inference_cpu_enabled
  inference_min_nodes        = var.inference_min_nodes
  node_service_account_email = module.identity.node_service_account_email
  labels                     = { component = "gke" }
}

module "alerts" {
  source = "../../modules/alerts"
  count  = var.lab_enabled ? 1 : 0

  project_id  = var.project_id
  environment = var.environment
  inference   = var.inference_cpu_enabled
}
