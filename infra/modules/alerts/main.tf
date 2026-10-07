data "google_monitoring_notification_channel" "email" {
  project      = var.project_id
  type         = "email"
  display_name = "${var.environment}-alerts"
}

locals {
  guide    = "See https://github.com/Josephdara/gke-platform/blob/main/platform/operations.md#investigating-an-unhealthy-service."
  requests = "sum by (namespace, job) (rate(http_requests_total{namespace=\"${var.environment}\"}[2m]))"
  alerts = {
    no-ready-replicas = {
      severity = "CRITICAL"
      duration = "120s"
      query    = "sum by (deployment) (kube_deployment_status_replicas_available{deployment=~\"${var.environment}-.+\"}) < 1"
      content  = "A Deployment in `${var.environment}` has had no available replicas for 2 minutes, so its service cannot answer. Likely causes: a release whose Pods crash or fail readiness, a secret the service cannot mount, or Pods that cannot be scheduled."
    }
    error-rate = {
      severity = "WARNING"
      duration = "300s"
      query    = "(sum by (namespace, job) (rate(http_requests_total{namespace=\"${var.environment}\",status=~\"5..\"}[2m])) / ${local.requests}) > 0.01 and ${local.requests} >= 1"
      content  = "More than 1% of a service's requests in `${var.environment}` returned a 5xx status for 5 minutes, while it handled at least 1 request per second. The `version` label names the release. Likely causes: a faulty release or a failing dependency."
    }
    latency = {
      severity = "WARNING"
      duration = "300s"
      query    = "histogram_quantile(0.95, sum by (namespace, job, le) (rate(http_request_duration_seconds_bucket{namespace=\"${var.environment}\"}[2m]))) > 0.5"
      content  = "A service's p95 latency in `${var.environment}` stayed above 500 ms for 5 minutes. Likely causes: CPU throttling at the container limit, the autoscaler at its maximum replicas, or a slow release."
    }
  }
}

resource "google_monitoring_alert_policy" "this" {
  for_each = local.alerts

  project               = var.project_id
  display_name          = "${var.environment}-${each.key}"
  combiner              = "OR"
  severity              = each.value.severity
  notification_channels = [data.google_monitoring_notification_channel.email.name]

  conditions {
    display_name = "${var.environment}-${each.key}"
    condition_prometheus_query_language {
      query                     = each.value.query
      duration                  = each.value.duration
      disable_metric_validation = true
    }
  }

  documentation {
    content   = "${each.value.content} ${local.guide}"
    mime_type = "text/markdown"
  }
}
