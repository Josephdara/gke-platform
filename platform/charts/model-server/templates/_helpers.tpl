{{- define "model-server.fullname" -}}
{{- $name := printf "%s-%s" .Values.environment .Values.serviceName -}}
{{- if gt (len $name) 63 -}}
{{- fail (printf "environment and serviceName combine to %q (%d characters). K8s names allow at most 63." $name (len $name)) -}}
{{- end -}}
{{- $name -}}
{{- end -}}

{{- define "model-server.namespace" -}}
{{- $namespace := printf "%s-inference" .Values.environment -}}
{{- if ne $namespace .Release.Namespace -}}
{{- fail (printf "Target namespace mismatch! Derived namespace is '%s', but release namespace is '%s'." $namespace .Release.Namespace) -}}
{{- end -}}
{{- $namespace -}}
{{- end -}}

{{- define "model-server.selectorLabels" -}}
app.kubernetes.io/name: {{ .Values.serviceName | quote }}
app.kubernetes.io/instance: {{ include "model-server.fullname" . | quote }}
{{- end -}}

{{- define "model-server.labels" -}}
{{ include "model-server.selectorLabels" . }}
project: {{ .Values.project | quote }}
environment: {{ .Values.environment | quote }}
service: {{ .Values.serviceName | quote }}
owner: {{ .Values.owner | quote }}
app.kubernetes.io/version: {{ .Values.releaseVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service | quote }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | quote }}
{{- end -}}

{{/*
Pod labels that identify the model. require-model-provenance checks them on
every Pod that runs a serving image.
*/}}
{{- define "model-server.modelLabels" -}}
component: model-server
model: {{ .Values.model.name | quote }}
model-revision: {{ .Values.model.revision | quote }}
{{- end -}}

{{/*
SHA-256 of the model's file list (path, size, and hash of every file), so one
annotation identifies exactly which files the Pod serves.
*/}}
{{- define "model-server.modelFingerprint" -}}
{{- $lines := list -}}
{{- range .Values.model.files -}}
{{- $lines = append $lines (printf "%s %d %s" .path (int64 .sizeBytes) .sha256) -}}
{{- end -}}
{{- $lines | sortAlpha | join "\n" | sha256sum -}}
{{- end -}}

{{- define "model-server.args" -}}
{{- $l := .Values.limits -}}
{{- if eq .Values.runtime "llamacpp" -}}
{{- $weights := (index .Values.model.files 0).path -}}
- --model
- {{ printf "/models/%s" $weights | quote }}
- --host
- "0.0.0.0"
- --port
- {{ .Values.server.port | quote }}
- --alias
- {{ .Values.model.servedName | quote }}
- --ctx-size
- {{ $l.contextTokens | quote }}
- --parallel
- {{ $l.concurrentSequences | quote }}
- --n-predict
- {{ $l.maxOutputTokens | quote }}
- --threads
- {{ .Values.server.threads | quote }}
- --metrics
- --no-slots
- --no-webui
{{- else -}}
- --model-id
- "/models"
- --hostname
- "0.0.0.0"
- --port
- {{ .Values.server.port | quote }}
- --max-concurrent-requests
- {{ $l.concurrentSequences | quote }}
- --json-output
{{- end -}}
{{- end -}}

{{/*
Requests must not exceed limits. The schema restricts units to m and Mi, so
the numbers compare directly.
*/}}
{{- define "model-server.validate" -}}
{{- $r := .Values.resources -}}
{{- range $key := list "cpu" "memory" "ephemeralStorage" -}}
{{- $request := index $r.requests $key -}}
{{- $limit := index $r.limits $key -}}
{{- if gt (regexReplaceAll "[^0-9]" $request "" | atoi) (regexReplaceAll "[^0-9]" $limit "" | atoi) -}}
{{- fail (printf "resources.requests.%s (%s) is above resources.limits.%s (%s). Lower the request or raise the limit." $key $request $key $limit) -}}
{{- end -}}
{{- end -}}
{{- $a := .Values.autoscaling -}}
{{- if $a.enabled -}}
{{- if eq (len $a.metrics) 0 -}}
{{- fail "autoscaling.enabled is true but autoscaling.metrics is empty. Add at least one queue metric." -}}
{{- end -}}
{{- if gt (int $a.min) (int $a.max) -}}
{{- fail (printf "autoscaling.min (%d) is above autoscaling.max (%d). Lower min or raise max." (int $a.min) (int $a.max)) -}}
{{- end -}}
{{- end -}}
{{- end -}}
