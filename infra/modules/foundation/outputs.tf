output "images_repository_id" {
  description = "ID of the image repository."
  value       = google_artifact_registry_repository.images.repository_id
}
