variable "project_id" {
  type        = string
  description = "Project that owns the secrets."
}

variable "environment" {
  type        = string
  description = "Prefix for secret IDs and Kubernetes service account names."
}

variable "secret_readers" {
  type = map(list(object({
    namespace = string
    service   = string
  })))
  description = "Readers per secret. Each secret becomes <environment>-<name>, readable only by the KSA <environment>-<service> in each listed namespace. The first reader's service labels the secret."

  validation {
    condition     = alltrue([for readers in values(var.secret_readers) : length(readers) > 0])
    error_message = "Every secret needs at least one reader; use ungranted_secrets for a secret with none."
  }
}

variable "ungranted_secrets" {
  type        = list(string)
  default     = []
  description = "Secrets created as <environment>-<name> with no grants, for refusal tests."
}
