output "node_service_account_member" {
  description = "IAM member string for the GKE node service account."
  value       = google_service_account.nodes.member
}
