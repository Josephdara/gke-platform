data "google_monitoring_notification_channel" "email" {
  project      = var.project_id
  type         = "email"
  display_name = "${var.environment}-alerts"
}

locals {
  guide     = "See https://github.com/Josephdara/gke-platform/blob/main/RUNBOOK.md#investigate-an-alert."
  env       = var.environment
  inference = "${var.environment}-inference"
  # rag-api's answers stream for tens of seconds, so the web-service latency and error alerts
  # leave it to the inference alerts below.
  requests = "sum by (namespace, job) (rate(http_requests_total{namespace=\"${local.env}\",job!=\"${local.env}-rag-api\"}[2m]))"
  rag      = "sum(rate(rag_requests_total{namespace=\"${local.env}\"}[10m]))"

  # Each alert names the label it groups on, so its email names the resource instead of __missing__.
  service_alerts = {
    no-ready-replicas = {
      severity = "CRITICAL"
      duration = "120s"
      subject  = "deployment"
      query    = "sum by (deployment) (kube_deployment_status_replicas_available{namespace=\"${local.env}\",deployment=~\"${local.env}-.+\",deployment!=\"${local.env}-rag-api\"}) < 1"
      content  = "A Deployment in `${local.env}` has had no available replicas for 2 minutes, so its service cannot answer. Likely causes: a release whose Pods crash or fail readiness, a secret the service cannot mount, or Pods that cannot be scheduled."
    }
    error-rate = {
      severity = "WARNING"
      duration = "300s"
      subject  = "job"
      query    = "(sum by (namespace, job) (rate(http_requests_total{namespace=\"${local.env}\",job!=\"${local.env}-rag-api\",status=~\"5..\"}[2m])) / ${local.requests}) > 0.01 and ${local.requests} >= 1"
      content  = "More than 1% of a service's requests in `${local.env}` returned a 5xx status for 5 minutes, while it handled at least 1 request per second. The `version` label names the release. Likely causes: a faulty release or a failing dependency."
    }
    latency = {
      severity = "WARNING"
      duration = "300s"
      subject  = "job"
      query    = "histogram_quantile(0.95, sum by (namespace, job, le) (rate(http_request_duration_seconds_bucket{namespace=\"${local.env}\",job!=\"${local.env}-rag-api\"}[2m]))) > 0.5"
      content  = "A service's p95 latency in `${local.env}` stayed above 500 ms for 5 minutes. Likely causes: CPU throttling at the container limit, the autoscaler at its maximum replicas, or a slow release."
    }
  }

  inference_alerts = {
    model-server-unavailable = {
      severity = "CRITICAL"
      duration = "300s"
      subject  = "deployment"
      query    = "sum by (deployment) (kube_deployment_status_replicas_available{namespace=\"${local.inference}\",deployment=~\"${local.env}-llm-.+\"}) < 1"
      content  = "A chat model server in `${local.inference}` has had no ready Pod for 5 minutes, so the assistant cannot answer. A cold start takes about 2 minutes; longer points to an unschedulable Pod, a failed model download, or a server that does not start."
    }
    rag-error-rate = {
      severity = "WARNING"
      duration = "60s"
      subject  = "namespace"
      query    = "sum by (namespace) (rate(rag_requests_total{namespace=\"${local.env}\",status!~\"complete|length|cancelled\"}[10m])) / ${local.rag} > 0.05 and ${local.rag} > 0"
      content  = "More than 5% of the assistant's answers over 10 minutes ended in an error. The `status` label of `rag_requests_total` names the kind: stalled, deadline, model_unavailable, retrieval_unavailable, or upstream_failed."
    }
    slow-first-token = {
      severity = "WARNING"
      duration = "600s"
      subject  = "namespace"
      query    = "histogram_quantile(0.95, sum by (namespace, le) (rate(rag_ttft_seconds_bucket{namespace=\"${local.env}\"}[10m]))) > 60"
      content  = "The assistant's p95 time to first token stayed above 60 seconds for 10 minutes. On CPU this means more requests are queued than llm-cpu's slots can serve: check the queue panel and whether the HPA added a second replica."
    }
    scaling-metric-missing = {
      severity = "WARNING"
      duration = "300s"
      subject  = "reason"
      query    = "label_replace(absent(llamacpp:requests_deferred{namespace=\"${local.inference}\"}), \"reason\", \"no samples\", \"\", \"\") or label_replace(max(kube_horizontalpodautoscaler_status_condition{namespace=\"${local.inference}\",condition=\"ScalingActive\",status=\"false\"}) == 1, \"reason\", \"HPA cannot read the metric\", \"\", \"\")"
      content  = "The HPA's scaling metric is missing for 5 minutes. With no samples, the model server or its scraping has stopped; when the HPA cannot read samples that exist, the custom metrics adapter has failed. Either way the replica count is frozen."
    }
    ingest-failed = {
      severity = "WARNING"
      duration = "0s"
      subject  = "pod"
      query    = "sum by (pod) (kube_pod_status_phase{namespace=\"${local.inference}\",pod=~\"${local.env}-ingest-.+\",phase=\"Failed\"}) > 0"
      content  = "An ingest run failed, so the corpus may be stale or incomplete. Its last log line is the run's report, with every failed document and why."
    }
    database-unavailable = {
      severity = "CRITICAL"
      duration = "300s"
      subject  = "statefulset"
      query    = "sum by (statefulset) (kube_statefulset_status_replicas_ready{namespace=\"${local.inference}\",statefulset=\"${local.env}-pgvector\"}) < 1"
      content  = "pgvector has had no ready Pod for 5 minutes, so retrieval and saved conversations fail."
    }
  }

  alerts = merge(local.service_alerts, var.inference ? local.inference_alerts : {})
}

resource "google_monitoring_alert_policy" "this" {
  for_each = local.alerts

  project               = var.project_id
  display_name          = "${local.env}-${each.key}"
  combiner              = "OR"
  severity              = each.value.severity
  notification_channels = [data.google_monitoring_notification_channel.email.name]

  conditions {
    display_name = "${local.env}-${each.key}"
    condition_prometheus_query_language {
      query                     = each.value.query
      duration                  = each.value.duration
      disable_metric_validation = true
    }
  }

  documentation {
    subject   = "${local.env}-${each.key}: $${metric.label.${each.value.subject}}"
    content   = "${each.value.content} ${local.guide}"
    mime_type = "text/markdown"
  }
}
