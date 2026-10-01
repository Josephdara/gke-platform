output "node_service_account_member" {
  description = "IAM member string for the GKE node service account."
  value       = google_service_account.nodes.member
}
output "node_service_account_email" {
  description = "Email of the GKE node service account."
  value       = google_service_account.nodes.email
}
