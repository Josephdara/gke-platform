{{- define "service.fullname" -}}
{{- $name := printf "%s-%s-%s" .Values.project .Values.environment .Values.serviceName -}}
{{- if gt (len $name) 63 -}}
{{- fail (printf "project, environment, and serviceName combine to %q (%d characters). K8s names allow at most 63." $name (len $name)) -}}
{{- end -}}
{{- $name -}}
{{- end -}}

{{- define "service.namespace" -}}
{{- $namespace := printf "%s-%s" .Values.project .Values.environment -}}
{{- if ne $namespace .Release.Namespace}}
    {{- fail (printf "Target namespace mismatch! Derived namespace is '%s', but release namespace is '%s'." $namespace .Release.Namespace) -}}
{{- end -}}
{{- $namespace -}}
{{- end -}}

{{- define "service.labels" -}}
{{ include "service.selectorLabels" . }}
project: {{ .Values.project | quote }}
environment: {{ .Values.environment | quote }}
service: {{ .Values.serviceName | quote }}
owner: {{ .Values.owner | quote }}
app.kubernetes.io/version: {{ .Values.releaseVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service | quote }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | quote }}
{{- end -}}

{{- define "service.selectorLabels" -}}
app.kubernetes.io/name: {{ .Values.serviceName | quote }}
app.kubernetes.io/instance: {{ include "service.fullname" . | quote }}
{{- end -}}

{{- define "service.serviceAccountName" -}}
{{- include "service.fullname" . -}}
{{- end -}}
