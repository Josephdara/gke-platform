output "cluster_name" {
  description = "Name of the GKE cluster."
  value       = google_container_cluster.super.name
}

output "dns_endpoint" {
  description = "DNS-based control plane endpoint."
  value       = google_container_cluster.super.control_plane_endpoints_config[0].dns_endpoint_config[0].endpoint
}