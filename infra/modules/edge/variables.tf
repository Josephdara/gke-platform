variable "project_id" {
  type        = string
  description = "Project that owns the DNS and certificate resources."
}

variable "environment" {
  type        = string
  description = "Environment prefix for resource names and the API hostname."
}

variable "dns_name" {
  type        = string
  description = "Subdomain delegated to Cloud DNS, without the trailing dot."
}

variable "lab_enabled" {
  type        = bool
  description = "Create the Gateway's static IP and the API's A record."
}
