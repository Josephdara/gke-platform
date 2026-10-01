output "network_id" {
  description = "ID of the VPC."
  value       = google_compute_network.this.id
}

output "subnetwork_id" {
  description = "ID of the node subnet."
  value       = google_compute_subnetwork.this.id
}

output "pods_range_name" {
  description = "Secondary range name for pod IPs."
  value       = google_compute_subnetwork.this.secondary_ip_range[0].range_name
}

output "services_range_name" {
  description = "Secondary range name for Service IPs."
  value       = google_compute_subnetwork.this.secondary_ip_range[1].range_name
}