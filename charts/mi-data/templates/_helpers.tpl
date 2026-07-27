{{/*
Expand the name of the chart.
*/}}
{{- define "mi-data.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "mi-data.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "mi-data.labels" -}}
helm.sh/chart: {{ include "mi-data.chart" . }}
{{ include "mi-data.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "mi-data.selectorLabels" -}}
app.kubernetes.io/name: {{ include "mi-data.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Renders a container image from a string or a dict with optional registry, repository, and tag.
Usage: {{ include "mi-data.image" .Values.image }}
*/}}
{{- define "mi-data.image" -}}
{{- if kindIs "string" . -}}
{{- . -}}
{{- else -}}
{{- if .registry -}}{{ .registry }}/{{ end -}}
{{- .repository -}}:{{- .tag -}}
{{- end -}}
{{- end -}}
