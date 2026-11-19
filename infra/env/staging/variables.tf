variable "project_id" {
  type    = string
  default = "gke-build-proj"
}
variable "environment" {
  type    = string
  default = "staging"
}
variable "zone" {
  type    = string
  default = "us-east4-a"
}
variable "region" {
  type    = string
  default = "us-east4"
}
variable "lab_enabled" {
  type        = bool
  description = "Create temporary infrastructure for GKE and VPC"
  default     = false
}
variable "inference_cpu_enabled" {
  type        = bool
  description = "Create the inference CPU node pool. Requires lab_enabled."
  default     = false

  validation {
    condition     = !var.inference_cpu_enabled || var.lab_enabled
    error_message = "inference_cpu_enabled requires lab_enabled=true."
  }
}
variable "inference_min_nodes" {
  type        = number
  description = "Minimum node count of the inference CPU pool, for warm scale-up tests."
  default     = 0

  validation {
    condition     = contains([0, 1, 2], var.inference_min_nodes)
    error_message = "inference_min_nodes must be 0, 1, or 2."
  }
}
variable "service" {
  type    = string
  default = "platform"
}
variable "owner" {
  type        = string
  default     = "jd"
  description = "Owner = Joseph Dara"
}
