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

  # Model Armor's own logging of screening operations would record the screened text.
  template_metadata {
    log_sanitize_operations = false
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
