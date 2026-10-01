variable "project_id" {
  type        = string
  description = "Project that owns the service accounts."
}

variable "environment" {
  type        = string
  description = "Environment prefix for service account IDs."
}
