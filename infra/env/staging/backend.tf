terraform {
  backend "gcs" {
    bucket = "gke-build-proj-staging-tfstate"
    prefix = "staging/"
  }
}