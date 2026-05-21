{{/*
Expand the name of the chart.
*/}}
{{- define "project-helm.name" -}}
{{- .Values.name | default .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "project-helm.fullname" -}}
{{- printf "%s" (include "project-helm.name" .) | trunc 63 | trimSuffix "-" | lower }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "project-helm.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "project-helm.labels" -}}
helm.sh/chart: {{ include "project-helm.chart" . }}
{{ include "project-helm.selectorLabels" . }}
app.kubernetes.io/version: {{ .Values.image.version | default .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app: {{ .Chart.Name }}
version: {{ .Chart.AppVersion | quote }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "project-helm.selectorLabels" -}}
app.kubernetes.io/name: {{ include "project-helm.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Label name list
*/}}
{{- define "project-helm.labelsList" -}}
- helm.sh/chart
- app.kubernetes.io/name
- app.kubernetes.io/instance
- app.kubernetes.io/version
- app.kubernetes.io/managed-by
- app
- version
{{- end }}

{{/*
Common environment variables.
APP_NAME is intentionally NOT emitted here; it is set explicitly per service
via .Values.env (see helm_values/base.yaml) so the application sees the bare
service name rather than the release name.
*/}}
{{- define "project-helm.CommonEnvironmentVariables" -}}
- name: TOTAL_INSTANCES_COUNT
  value: {{ .Values.deployment.replicas | quote }}
{{- end }}
