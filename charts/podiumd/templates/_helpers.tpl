{{/*
Expand the name of the chart.
*/}}
{{- define "podiumd.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "podiumd.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "podiumd.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "podiumd.labels" -}}
helm.sh/chart: {{ include "podiumd.chart" . }}
{{ include "podiumd.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "podiumd.selectorLabels" -}}
app.kubernetes.io/name: {{ include "podiumd.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "podiumd.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "podiumd.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Frontend labels
*/}}
{{- define "podiumd.labelsFrontend" -}}
{{ include "podiumd.labels" . }}
{{ include "podiumd.selectorLabelsFrontend" . }}
{{- end }}

{{/*
Frontend selector labels
*/}}
{{- define "podiumd.selectorLabelsFrontend" -}}
app.kubernetes.io/name: {{ include "podiumd.name" . }}-frontend
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Adapter labels
*/}}
{{- define "podiumd.labelsAdapter" -}}
{{ include "podiumd.labels" . }}
{{ include "podiumd.selectorLabelsAdapter" . }}
{{- end }}

{{/*
Adapter selector labels
*/}}
{{- define "podiumd.selectorLabelsAdapter" -}}
app.kubernetes.io/name: {{ include "podiumd.name" . }}-adapter
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Expand the name of the chart.
*/}}
{{- define "api-proxy.name" -}}
{{- default "api-proxy" .Values.apiproxy.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified name for api-proxy.
We truncate at 52 chars in order to provide space for the "-api-proxy" suffix
*/}}
{{- define "api-proxy.fullname" -}}
{{- if .Values.apiproxy.fullnameOverride }}
{{- .Values.apiproxy.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{ include "podiumd.fullname" . | trunc 53 | trimSuffix "-" }}-api-proxy
{{- end }}
{{- end }}