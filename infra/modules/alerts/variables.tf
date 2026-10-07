variable "project_id" {
  type        = string
  description = "Project that owns the alert policies."
}

variable "environment" {
  type        = string
  description = "Namespace the alerts watch, and the prefix of the <environment>-alerts notification channel."
}
