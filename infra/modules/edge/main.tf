locals {
  api_host = "api.${var.environment}.${var.dns_name}"
  hosts    = { for h in var.hosts : h => "${h}.${var.environment}.${var.dns_name}" }
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

resource "google_certificate_manager_dns_authorization" "host" {
  for_each = local.hosts

  project         = var.project_id
  name            = "${var.environment}-${each.key}-dns-auth"
  domain          = each.value
  deletion_policy = "PREVENT"
}

resource "google_dns_record_set" "host_authorization" {
  for_each = local.hosts

  project      = var.project_id
  managed_zone = google_dns_managed_zone.this.name
  name         = google_certificate_manager_dns_authorization.host[each.key].dns_resource_record[0].name
  type         = google_certificate_manager_dns_authorization.host[each.key].dns_resource_record[0].type
  ttl          = 300
  rrdatas      = [google_certificate_manager_dns_authorization.host[each.key].dns_resource_record[0].data]
}

resource "google_certificate_manager_certificate" "host" {
  for_each = local.hosts

  project         = var.project_id
  name            = "${var.environment}-${each.key}-cert"
  deletion_policy = "PREVENT"

  managed {
    domains            = [each.value]
    dns_authorizations = [google_certificate_manager_dns_authorization.host[each.key].id]
  }
}

resource "google_certificate_manager_certificate_map" "this" {
  project         = var.project_id
  name            = "${var.environment}-cert-map"
  deletion_policy = "PREVENT"
}

resource "google_certificate_manager_certificate_map_entry" "host" {
  for_each = local.hosts

  project         = var.project_id
  name            = "${var.environment}-${each.key}"
  map             = google_certificate_manager_certificate_map.this.name
  hostname        = each.value
  certificates    = [google_certificate_manager_certificate.host[each.key].id]
  deletion_policy = "PREVENT"
}

moved {
  from = google_certificate_manager_dns_authorization.api
  to   = google_certificate_manager_dns_authorization.host["api"]
}

moved {
  from = google_dns_record_set.api_authorization
  to   = google_dns_record_set.host_authorization["api"]
}

moved {
  from = google_certificate_manager_certificate.api
  to   = google_certificate_manager_certificate.host["api"]
}

moved {
  from = google_certificate_manager_certificate_map_entry.api
  to   = google_certificate_manager_certificate_map_entry.host["api"]
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
