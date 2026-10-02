variable "project_id" {
  type        = string
  description = "Project that owns the pipeline resources."
}

variable "region" {
  type        = string
  description = "Region for the bucket, repository link, and triggers. Must match the connection."
}

variable "environment" {
  type        = string
  description = "Environment prefix for trigger names."
}

variable "name_prefix" {
  type        = string
  description = "Prefix for globally unique names, <project>-<environment>."
}

variable "labels" {
  type        = map(string)
  default     = {}
  description = "Labels added to the provider's default labels for this module's resources."
}

variable "connection_id" {
  type        = string
  description = "Full name of the manually created Cloud Build GitHub connection."
}

variable "repository_uri" {
  type        = string
  description = "HTTPS clone URL of the GitHub repository."
}

variable "validate_service_account_id" {
  type        = string
  description = "ID of the service account for pull request validation builds."
}

variable "publish_service_account_id" {
  type        = string
  description = "ID of the service account for image publication builds."
}

variable "images_repository_id" {
  type        = string
  description = "ID of the Artifact Registry image repository."
}