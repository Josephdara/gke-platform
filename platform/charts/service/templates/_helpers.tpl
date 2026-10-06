{{- define "service.fullname" -}}
{{- $name := printf "%s-%s" .Values.environment .Values.serviceName -}}
{{- if gt (len $name) 63 -}}
{{- fail (printf "environment and serviceName combine to %q (%d characters). K8s names allow at most 63." $name (len $name)) -}}
{{- end -}}
{{- $name -}}
{{- end -}}

{{- define "service.namespace" -}}
{{- $namespace := .Values.environment -}}
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

{{/*
Requests must not exceed limits. The schema restricts units to m and Mi, so the numbers compare directly.
*/}}
{{- define "service.validateResources" -}}
{{- $r := .Values.resources -}}
{{- if gt (trimSuffix "m" $r.requests.cpu | atoi) (trimSuffix "m" $r.limits.cpu | atoi) -}}
{{- fail (printf "resources.requests.cpu (%s) is above resources.limits.cpu (%s). Lower the request or raise the limit." $r.requests.cpu $r.limits.cpu) -}}
{{- end -}}
{{- if gt (trimSuffix "Mi" $r.requests.memory | atoi) (trimSuffix "Mi" $r.limits.memory | atoi) -}}
{{- fail (printf "resources.requests.memory (%s) is above resources.limits.memory (%s). Lower the request or raise the limit." $r.requests.memory $r.limits.memory) -}}
{{- end -}}
{{- end -}}

{{- define "service.secretsDir" -}}
/var/secrets
{{- end -}}

{{- define "service.validateSecrets" -}}
{{- $names := list -}}
{{- $envs := list -}}
{{- range .Values.secrets -}}
{{- $names = append $names .name -}}
{{- $envs = append $envs .env -}}
{{- end -}}
{{- if or (ne (len $names) (len (uniq $names))) (ne (len $envs) (len (uniq $envs))) -}}
{{- fail "secrets lists the same name or env more than once. Remove the duplicate entry." -}}
{{- end -}}
{{- end -}}

{{- define "service.validateReplicas" -}}
{{- if gt (int .Values.replicas.min) (int .Values.replicas.max) -}}
{{- fail (printf "replicas.min (%d) is above replicas.max (%d). Lower min or raise max." (int .Values.replicas.min) (int .Values.replicas.max)) -}}
{{- end -}}
{{- end -}}
