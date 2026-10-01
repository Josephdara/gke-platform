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
  default = "us-east4-b"
}
variable "region" {
  type    = string
  default = "us-east4"
}
variable "lab_enabled" {
  type        = bool
  description = "Create temporary infrastructure for GKE and VPC"
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
