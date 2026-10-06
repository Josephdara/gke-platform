variable "project_id" {
  type        = string
  description = "Project that owns the APIs and the image repository."
}

variable "region" {
  type        = string
  description = "Region for the image repository."
}

variable "environment" {
  type        = string
  description = "Environment prefix for new resource names, <environment>-<purpose>."
}

variable "name_prefix" {
  type        = string
  description = "Prefix for resource names, <project>-<environment>."
}

variable "labels" {
  type        = map(string)
  default     = {}
  description = "Labels added to the provider's default labels for this module's resources."
}
