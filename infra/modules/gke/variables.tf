variable "project_id" {
  type = string
}

variable "environment" {
  type = string
}

variable "zone" {
  type = string
}

variable "labels" {
  type = map(string)
}

variable "network_id" {
  type = string
}

variable "subnet_id" {
  type = string
}

variable "pods_range_id" {
  type = string
}

variable "services_range_id" {
  type = string
}

variable "node_service_account_email" {
  type = string
}
