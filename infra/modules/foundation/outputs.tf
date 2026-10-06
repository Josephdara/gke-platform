output "images_repository_id" {
  description = "ID of the image repository."
  value       = google_artifact_registry_repository.images.repository_id
}

output "mirror_repository_id" {
  description = "ID of the controller image mirror repository."
  value       = google_artifact_registry_repository.mirror.repository_id
}
