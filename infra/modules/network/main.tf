resource "google_compute_network" "this" {
  project                 = var.project_id
  name                    = "${var.environment}-vpc"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"

}
resource "google_compute_subnetwork" "this" {
  project                  = var.project_id
  name                     = "${var.environment}-nodes-subnet"
  network                  = google_compute_network.this.name
  ip_cidr_range            = "10.40.0.0/24"
  region                   = var.region
  private_ip_google_access = true
  secondary_ip_range {
    range_name    = "pods-range"
    ip_cidr_range = "10.41.0.0/20"
  }
  secondary_ip_range {
    range_name    = "services-range"
    ip_cidr_range = "10.42.0.0/24"
  }
  depends_on = [google_compute_network.this]
}
resource "google_compute_router" "cloud_router" {
  project    = var.project_id
  name       = "${var.environment}-router"
  region     = var.region
  network    = google_compute_network.this.name
  depends_on = [google_compute_subnetwork.this]
}
resource "google_compute_router_nat" "cloud_nat" {
  project                            = var.project_id
  name                               = "${var.environment}-nat"
  router                             = google_compute_router.cloud_router.name
  region                             = var.region
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"
  nat_ip_allocate_option             = "AUTO_ONLY"

  subnetwork {
    name                    = google_compute_subnetwork.this.name
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
  }
  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}
resource "google_dns_managed_zone" "googleapis" {
  project     = var.project_id
  name        = "${var.environment}-googleapis"
  dns_name    = "googleapis.com."
  description = "Resolves Google API names to private.googleapis.com inside the VPC"
  visibility  = "private"

  private_visibility_config {
    networks {
      network_url = google_compute_network.this.id
    }
  }
}

resource "google_dns_record_set" "private_googleapis" {
  project      = var.project_id
  managed_zone = google_dns_managed_zone.googleapis.name
  name         = "private.googleapis.com."
  type         = "A"
  ttl          = 300
  rrdatas      = ["199.36.153.8", "199.36.153.9", "199.36.153.10", "199.36.153.11"]
}

resource "google_dns_record_set" "googleapis_wildcard" {
  project      = var.project_id
  managed_zone = google_dns_managed_zone.googleapis.name
  name         = "*.googleapis.com."
  type         = "CNAME"
  ttl          = 300
  rrdatas      = ["private.googleapis.com."]
}
