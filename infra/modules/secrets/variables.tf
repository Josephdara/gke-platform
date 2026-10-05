variable "project_id" {
  type        = string
  description = "Project that owns the secrets."
}

variable "environment" {
  type        = string
  description = "Prefix for secret IDs, and the namespace of the workloads that read them."
}

variable "service_secrets" {
  type        = map(list(string))
  description = "Secret names per service. Each becomes <environment>-<service>-<name>, readable only by that service's KSA."
}

variable "ungranted_secrets" {
  type        = list(string)
  default     = []
  description = "Secrets created as <environment>-<name> with no grants, for refusal tests."
}
