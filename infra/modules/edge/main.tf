locals {
  api_host = "api.${var.environment}.${var.dns_name}"
}

resource "google_dns_managed_zone" "this" {
  project         = var.project_id
  name            = "${var.environment}-dns"
  dns_name        = "${var.dns_name}."
  deletion_policy = "PREVENT"

  dnssec_config {
    state = "on"
  }
}

resource "google_certificate_manager_dns_authorization" "api" {
  project         = var.project_id
  name            = "${var.environment}-api-dns-auth"
  domain          = local.api_host
  deletion_policy = "PREVENT"
}

resource "google_dns_record_set" "api_authorization" {
  project      = var.project_id
  managed_zone = google_dns_managed_zone.this.name
  name         = google_certificate_manager_dns_authorization.api.dns_resource_record[0].name
  type         = google_certificate_manager_dns_authorization.api.dns_resource_record[0].type
  ttl          = 300
  rrdatas      = [google_certificate_manager_dns_authorization.api.dns_resource_record[0].data]
}

resource "google_certificate_manager_certificate" "api" {
  project         = var.project_id
  name            = "${var.environment}-api-cert"
  deletion_policy = "PREVENT"

  managed {
    domains            = [local.api_host]
    dns_authorizations = [google_certificate_manager_dns_authorization.api.id]
  }
}

resource "google_certificate_manager_certificate_map" "this" {
  project         = var.project_id
  name            = "${var.environment}-cert-map"
  deletion_policy = "PREVENT"
}

resource "google_certificate_manager_certificate_map_entry" "api" {
  project         = var.project_id
  name            = "${var.environment}-api"
  map             = google_certificate_manager_certificate_map.this.name
  hostname        = local.api_host
  certificates    = [google_certificate_manager_certificate.api.id]
  deletion_policy = "PREVENT"
}

resource "google_compute_global_address" "gateway" {
  count   = var.lab_enabled ? 1 : 0
  project = var.project_id
  name    = "${var.environment}-gateway-ip"
}

resource "google_dns_record_set" "api" {
  count        = var.lab_enabled ? 1 : 0
  project      = var.project_id
  managed_zone = google_dns_managed_zone.this.name
  name         = "${local.api_host}."
  type         = "A"
  ttl          = 300
  rrdatas      = [google_compute_global_address.gateway[0].address]
}
