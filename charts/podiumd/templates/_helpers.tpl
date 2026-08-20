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
helm.sh/chart: {{ include "podiumd.chart" . }}
{{ include "podiumd.selectorLabelsFrontend" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
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
helm.sh/chart: {{ include "podiumd.chart" . }}
{{ include "podiumd.selectorLabelsAdapter" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Adapter selector labels
*/}}
{{- define "podiumd.selectorLabelsAdapter" -}}
app.kubernetes.io/name: {{ include "podiumd.name" . }}-adapter
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Common labels with an explicit app.kubernetes.io/name override — for
sub-components (e.g. frankgateway's shim/oauth2-proxy/etcd/dashboard) that
need a name distinct from the chart-wide default. Unlike labelsFrontend /
labelsAdapter above, the override name is a call-site argument rather than a
fixed suffix, and it replaces app.kubernetes.io/name outright instead of
relying on a second, later occurrence of the same key winning in rendered
YAML.
Usage: {{ include "podiumd.labelsNamed" (dict "context" $ "name" "frankgateway-shim") }}
*/}}
{{- define "podiumd.labelsNamed" -}}
helm.sh/chart: {{ include "podiumd.chart" .context }}
{{ include "podiumd.selectorLabelsNamed" . }}
{{- if .context.Chart.AppVersion }}
app.kubernetes.io/version: {{ .context.Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .context.Release.Service }}
{{- end }}

{{/*
Selector labels with an explicit app.kubernetes.io/name override — see
podiumd.labelsNamed.
*/}}
{{- define "podiumd.selectorLabelsNamed" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .context.Release.Name }}
{{- end }}

{{/*
Renders a container image from a string or a dict with optional registry, repository, and tag.
Usage: {{ include "podiumd.image" .Values.path.to.image }}
*/}}
{{- define "podiumd.image" -}}
{{- if kindIs "string" . -}}
{{- . -}}
{{- else -}}
{{- if .registry -}}{{ .registry }}/{{ end -}}
{{- .repository -}}:{{- .tag -}}
{{- end -}}
{{- end -}}

{{/*
Renders a value that contains template.
Usage:
{{ include "kiss-frontend.tplvalues.render" ( dict "value" .Values.path.to.the.Value "context" $) }}
*/}}
{{- define "kiss-frontend.tplvalues.render" -}}
    {{- if typeIs "string" .value }}
        {{- tpl .value .context }}
    {{- else }}
        {{- tpl (.value | toYaml) .context }}
    {{- end }}
{{- end -}}