# Model Armor screens the assistant's questions, retrieved passages, and answers. rag-api calls it
# with this template; MODEL_ARMOR_MODE in rag-api's values decides whether results only get
# recorded or also block. The template and the grant persist; screening only happens in a session.
resource "google_model_armor_template" "assistant" {
  project     = var.project_id
  location    = var.region
  template_id = "${var.environment}-assistant"
  labels      = { component = "assistant" }

  filter_config {
    pi_and_jailbreak_filter_settings {
      filter_enforcement = "ENABLED"
      confidence_level   = "MEDIUM_AND_ABOVE"
    }
    malicious_uri_filter_settings {
      filter_enforcement = "ENABLED"
    }
    sdp_settings {
      basic_config {
        filter_enforcement = "ENABLED"
      }
    }
    rai_settings {
      dynamic "rai_filters" {
        for_each = ["HATE_SPEECH", "HARASSMENT", "SEXUALLY_EXPLICIT", "DANGEROUS"]
        content {
          filter_type      = rai_filters.value
          confidence_level = "MEDIUM_AND_ABOVE"
        }
      }
    }
  }

  # Model Armor logs every screening operation, including the screened text, to Cloud Logging, so
  # each violation can be reviewed in staging. Staging screens only the evaluation set, the corpus
  # and test questions.
  template_metadata {
    log_sanitize_operations = true
    log_template_operations = false
  }

  depends_on = [module.foundation]
}

resource "google_project_iam_member" "rag_api_model_armor" {
  project = var.project_id
  role    = "roles/modelarmor.user"
  member  = "principal://iam.googleapis.com/${module.secrets.workload_pool}/subject/ns/${var.environment}/sa/${var.environment}-rag-api"
}

output "model_armor_template" {
  description = "The template rag-api's MODEL_ARMOR_TEMPLATE names."
  value       = google_model_armor_template.assistant.id
}

# Model Armor answers only on its regional hostname, which private.googleapis.com does not serve,
# so a Private Service Connect endpoint carries the calls inside the VPC. A private zone for that one
# hostname points at the endpoint; every other Google API name still uses the googleapis zone.
# NetworkPolicy allows rag-api to reach this address, so it stays fixed.
locals {
  model_armor_host     = "modelarmor.${var.region}.rep.googleapis.com"
  model_armor_address  = "10.40.0.250"
  model_armor_endpoint = var.lab_enabled && var.inference_cpu_enabled
}

resource "google_network_connectivity_regional_endpoint" "model_armor" {
  count             = local.model_armor_endpoint ? 1 : 0
  project           = var.project_id
  location          = var.region
  name              = "${var.environment}-model-armor"
  target_google_api = local.model_armor_host
  access_type       = "REGIONAL"
  network           = module.network[0].network_id
  subnetwork        = module.network[0].subnetwork_id
  address           = local.model_armor_address
}

resource "google_dns_managed_zone" "model_armor" {
  count       = local.model_armor_endpoint ? 1 : 0
  project     = var.project_id
  name        = "${var.environment}-model-armor"
  dns_name    = "${local.model_armor_host}."
  description = "Resolves Model Armor's regional hostname to its Private Service Connect endpoint"
  visibility  = "private"

  private_visibility_config {
    networks {
      network_url = module.network[0].network_id
    }
  }
}

resource "google_dns_record_set" "model_armor" {
  count        = local.model_armor_endpoint ? 1 : 0
  project      = var.project_id
  managed_zone = google_dns_managed_zone.model_armor[0].name
  name         = google_dns_managed_zone.model_armor[0].dns_name
  type         = "A"
  ttl          = 300
  rrdatas      = [google_network_connectivity_regional_endpoint.model_armor[0].address]
}
