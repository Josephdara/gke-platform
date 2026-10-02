output "node_service_account_member" {
  description = "IAM member string for the GKE node service account."
  value       = google_service_account.nodes.member
}
output "node_service_account_email" {
  description = "Email of the GKE node service account."
  value       = google_service_account.nodes.email
}

output "ci_build_publish_id" {
  description = "Email for CI publishing service account "
  value       = google_service_account.build_publish.id
}

output "ci_build_validate_id" {
  description = "Email for CI validation service account "
  value       = google_service_account.build_validate.id
}

output "ci_build_publish_member" {
  description = "Email for CI publishing service account "
  value       = google_service_account.build_publish.member
}