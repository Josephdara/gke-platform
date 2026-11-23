# One dashboard for inference sessions: the assistant's traffic and latency, the model server's
# queue, scaling, and resources, and Model Armor's checks. Every panel is a PromQL query over
# Managed Service for Prometheus data and GKE system metrics.
locals {
  panels = [
    { title = "Answers by outcome (per second)", queries = { "{{status}}" = "sum by (status) (rate(rag_requests_total{namespace=\"${local.env}\"}[5m]))" } },
    { title = "Refused before generation (per second)", queries = { "{{reason}}" = "sum by (reason) (rate(rag_rejections_total{namespace=\"${local.env}\"}[5m]))" } },
    { title = "Time to first token (s)", queries = {
      p50 = "histogram_quantile(0.5, sum by (le) (rate(rag_ttft_seconds_bucket{namespace=\"${local.env}\"}[5m])))"
      p95 = "histogram_quantile(0.95, sum by (le) (rate(rag_ttft_seconds_bucket{namespace=\"${local.env}\"}[5m])))"
    } },
    { title = "Completion time (s)", queries = {
      p50 = "histogram_quantile(0.5, sum by (le) (rate(rag_completion_seconds_bucket{namespace=\"${local.env}\"}[5m])))"
      p95 = "histogram_quantile(0.95, sum by (le) (rate(rag_completion_seconds_bucket{namespace=\"${local.env}\"}[5m])))"
    } },
    { title = "Retrieval time, p95 (s)", queries = { p95 = "histogram_quantile(0.95, sum by (le) (rate(rag_retrieval_seconds_bucket{namespace=\"${local.env}\"}[5m])))" } },
    { title = "Generated tokens per second", queries = { "{{pod}}" = "sum by (pod) (rate(llamacpp:tokens_predicted_total{namespace=\"${local.inference}\"}[5m]))" } },
    { title = "Queued and running requests per Pod", queries = {
      "queued {{pod}}"  = "max by (pod) (llamacpp:requests_deferred{namespace=\"${local.inference}\"})"
      "running {{pod}}" = "max by (pod) (llamacpp:requests_processing{namespace=\"${local.inference}\"})"
    } },
    { title = "KV cache usage", queries = { "{{pod}}" = "max by (pod) (llamacpp:kv_cache_usage_ratio{namespace=\"${local.inference}\"})" } },
    { title = "HPA replicas", queries = {
      "desired {{horizontalpodautoscaler}}" = "max by (horizontalpodautoscaler) (kube_horizontalpodautoscaler_status_desired_replicas{namespace=\"${local.inference}\"})"
      "current {{horizontalpodautoscaler}}" = "max by (horizontalpodautoscaler) (kube_horizontalpodautoscaler_status_current_replicas{namespace=\"${local.inference}\"})"
    } },
    { title = "Nodes and pending Pods", queries = {
      nodes                   = "count(kubernetes_io:node_cpu_allocatable_cores{monitored_resource=\"k8s_node\"})"
      "pending {{namespace}}" = "sum by (namespace) (kube_pod_status_phase{phase=\"Pending\"})"
    } },
    { title = "Model server CPU and memory (share of limit)", queries = {
      "cpu {{container_name}}"    = "max by (container_name) (kubernetes_io:container_cpu_limit_utilization{monitored_resource=\"k8s_container\",namespace_name=\"${local.inference}\"})"
      "memory {{container_name}}" = "max by (container_name) (kubernetes_io:container_memory_limit_utilization{monitored_resource=\"k8s_container\",namespace_name=\"${local.inference}\",memory_type=\"non-evictable\"})"
    } },
    { title = "Serving release", queries = { "{{job}} {{version}}" = "count by (job, version) (up{namespace=~\"${local.env}|${local.inference}\"})" } },
    { title = "Model Armor checks (per second)", queries = { "{{point}} {{result}}" = "sum by (point, result) (rate(rag_guardrail_checks_total{namespace=\"${local.env}\"}[5m]))" } },
    { title = "Model Armor check time, p95 (s)", queries = { "{{point}}" = "histogram_quantile(0.95, sum by (point, le) (rate(rag_guardrail_seconds_bucket{namespace=\"${local.env}\"}[5m])))" } },
  ]
}

resource "google_monitoring_dashboard" "inference" {
  count   = var.inference ? 1 : 0
  project = var.project_id
  dashboard_json = jsonencode({
    displayName = "${local.env}-inference"
    mosaicLayout = {
      columns = 48
      tiles = [for i, panel in local.panels : {
        xPos   = (i % 2) * 24
        yPos   = floor(i / 2) * 16
        width  = 24
        height = 16
        widget = {
          title = panel.title
          xyChart = {
            dataSets = [for legend, query in panel.queries : {
              timeSeriesQuery = { prometheusQuery = query }
              plotType        = "LINE"
              legendTemplate  = legend
            }]
          }
        }
      }]
    }
  })
}
