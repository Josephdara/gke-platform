output "images_repository_id" {
  description = "ID of the image repository."
  value       = google_artifact_registry_repository.images.repository_id
}

output "mirror_repository_id" {
  description = "ID of the controller image mirror repository."
  value       = google_artifact_registry_repository.mirror.repository_id
}

output "models_bucket_name" {
  description = "Name of the bucket that holds model files and corpus snapshots."
  value       = google_storage_bucket.models.name
}
