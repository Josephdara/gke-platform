output "evidence_bucket_name" {
  description = "Name of the build evidence bucket."
  value       = google_storage_bucket.evidence.name
}