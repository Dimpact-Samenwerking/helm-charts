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
{{/*
Chart name+version for the helm.sh/chart label.

Truncated to 63 chars (the label-value limit), then stripped of any trailing
characters a label may not end with. The stock helm scaffold only trims "-",
which is not enough: a long snapshot version from a branch name can land the
cut on a "." and produce an invalid label, failing the whole release at
admission time with an error that points at whichever object happened to be
applied first (in practice a pre-upgrade hook Job) rather than at the version
string that actually caused it.
*/}}
{{- define "podiumd.chart" -}}
{{- $c := printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 -}}
{{- regexReplaceAll "[^a-zA-Z0-9]+$" $c "" -}}
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
Frank!Gateway — object name for one gateway instance.

Every instance is named after its key: `frankgateway-<key>`. There is no
reserved key and no bare `frankgateway` name — the traffic-class split is the
only shape this chart renders. `nameOverride` wins if set.

Usage: {{ include "podiumd.frankgateway.instanceName" (dict "key" $key "instance" $inst) }}
*/}}
{{- define "podiumd.frankgateway.instanceName" -}}
{{- if .instance.nameOverride -}}
{{- .instance.nameOverride -}}
{{- else -}}
frankgateway-{{ .key }}
{{- end -}}
{{- end -}}

{{/*
Frank!Gateway — etcd prefix for one gateway instance.

All instances share the single etcd StatefulSet; isolation comes from the
prefix, because APISIX in traditional mode loads exactly the objects beneath
its configured prefix. One rule, no exception: `/frankgateway-<key>`,
overridable per instance with `etcdPrefix`.

Usage: {{ include "podiumd.frankgateway.etcdPrefix" (dict "key" $key "instance" $inst) }}
*/}}
{{- define "podiumd.frankgateway.etcdPrefix" -}}
{{- if .instance.etcdPrefix -}}
{{- .instance.etcdPrefix -}}
{{- else -}}
/frankgateway-{{ .key }}
{{- end -}}
{{- end -}}

{{/*
Frank!Gateway — effective values for one gateway instance.

Deep-merges the per-instance override over the shared `frankgateway` block, so
an instance only has to state what differs. `instances` is dropped from the
result to avoid carrying the whole map into every instance.

Returns YAML; consume with `fromYaml`:
  {{- $inst := include "podiumd.frankgateway.instanceValues"
        (dict "root" $ "key" $key "override" $override) | fromYaml }}
*/}}
{{- define "podiumd.frankgateway.instanceValues" -}}
{{- $shared := omit .root.Values.frankgateway "instances" -}}
{{- $merged := mergeOverwrite (deepCopy $shared) (deepCopy (.override | default dict)) -}}
{{- toYaml $merged -}}
{{- end -}}

{{/*
Frank!Gateway — topologySpreadConstraints for one workload.

Two replicas on the same node survive a pod crash but not a node drain, which
is the disruption that actually happens on AKS (node image upgrades, autoscaler
consolidation). Spread them.

`whenUnsatisfiable: DoNotSchedule`, i.e. a hard requirement, not a preference:
every environment this chart targets is multi-node, so co-located replicas are
a fault to surface rather than a compromise to accept. A replica that cannot be
placed on its own node stays Pending — visible, and on a cluster with the
autoscaler enabled, a trigger to add a node. `ScheduleAnyway` would instead
place both replicas on one node and leave a deployment that looks highly
available and is not.

An instance may replace the whole list via `topologySpreadConstraints`.

Usage: {{ include "podiumd.frankgateway.spread" (dict "name" $name "override" $fg.topologySpreadConstraints) }}
*/}}
{{- define "podiumd.frankgateway.spread" -}}
{{- with .override -}}
{{- toYaml . -}}
{{- else -}}
- maxSkew: 1
  topologyKey: kubernetes.io/hostname
  whenUnsatisfiable: DoNotSchedule
  labelSelector:
    matchLabels:
      app.kubernetes.io/name: {{ .name }}
{{- end -}}
{{- end -}}

{{/*
Frank!Gateway — etcd client endpoints, one per member.

Addresses the members individually through the headless Service rather than the
load-balanced client Service: an APISIX or dashboard client given a single
round-robin address has no way to fail over to a healthy member when the one it
dialled dies mid-connection — it just errors. Given the full list it does.

Usage: {{ include "podiumd.frankgateway.etcdEndpoints" (dict "root" $root "indent" 6) }}
*/}}
{{- define "podiumd.frankgateway.etcdEndpoints" -}}
{{- $root := .root -}}
{{- $ns := $root.Release.Namespace -}}
{{- range $i := until (int $root.Values.frankgateway.etcd.replicas) }}
- "http://frankgateway-etcd-{{ $i }}.frankgateway-etcd-headless.{{ $ns }}.svc.cluster.local:2379"
{{- end }}
{{- end -}}

{{/*
Frank!Gateway — Admin API credentials for one gateway instance.

Values override wins; otherwise the existing Secret is looked up so generated
keys stay stable across upgrades; otherwise random 32-char values are generated
on first install. The upstream public default keys are never used.

Derivation lives in a helper because both the config Secret and the gateway
Deployment's config checksum need the same values — computing them twice with
different logic would let the checksum drift from the config it describes.

Returns YAML; consume with `fromYaml`:
  {{- $creds := include "podiumd.frankgateway.adminCreds"
        (dict "root" $ "instance" $inst "name" $name) | fromYaml }}
*/}}
{{- define "podiumd.frankgateway.adminCreds" -}}
{{- $admin := .instance.admin.adminKey | default "" -}}
{{- $viewer := .instance.admin.viewerKey | default "" -}}
{{- $existing := lookup "v1" "Secret" .root.Release.Namespace (printf "%s-admin-credentials" .name) -}}
{{- if and (eq $admin "") $existing -}}
{{-   $admin = index $existing.data "admin" | default "" | b64dec -}}
{{- end -}}
{{- if and (eq $viewer "") $existing -}}
{{-   $viewer = index $existing.data "viewer" | default "" | b64dec -}}
{{- end -}}
{{- if eq $admin "" }}{{- $admin = randAlphaNum 32 }}{{- end -}}
{{- if eq $viewer "" }}{{- $viewer = randAlphaNum 32 }}{{- end -}}
admin: {{ $admin | quote }}
viewer: {{ $viewer | quote }}
{{- end -}}

{{/*
Frank!Gateway — APISIX config.yaml body for one gateway instance.

Rendered from a helper rather than inline so the gateway Deployment can take a
checksum of *its own* instance's config: a range over instances in the config
template would otherwise give every Deployment the same whole-file checksum, so
a change to one instance would roll all of them.

Usage: {{ include "podiumd.frankgateway.config"
          (dict "root" $ "instance" $inst "name" $name "prefix" $prefix
                "admin" $admin "viewer" $viewer) }}
*/}}
{{- define "podiumd.frankgateway.config" -}}
{{- $fg := .instance -}}
apisix:
  node_listen: 9080
  enable_ipv6: false
  # Where `require("openbao-secret-header")` resolves from: the Lua shipped in
  # files/frankgateway/, mounted from the frankgateway-lua ConfigMap. Without
  # this the route's serverless function fails to load and every request
  # through it errors.
  extra_lua_path: "/usr/local/apisix/conf/lua/?.lua"
  {{- if $fg.tls.enabled }}
  # TLS data-plane listener; per-SNI certificates come from SSL objects
  # in etcd (seeded via the Admin API), not from mounted files.
  ssl:
    enable: true
    listen:
      - port: {{ $fg.tls.port }}
  {{- end }}

  enable_control: true
  control:
    ip: "0.0.0.0"
    port: 9092

deployment:
  admin:
    # ClusterIP-only Service; the Admin API is additionally protected by
    # the random admin key below. Tighten per-env if required.
    allow_admin:
      - 0.0.0.0/0

    admin_key:
      - name: "admin"
        key: {{ .admin | quote }}
        role: admin
      - name: "viewer"
        key: {{ .viewer | quote }}
        role: viewer

  etcd:
    host:
      {{- include "podiumd.frankgateway.etcdEndpoints" (dict "root" .root) | nindent 6 }}
    prefix: {{ .prefix | quote }}
    timeout: 30

plugin_attr:
  prometheus:
    export_addr:
      ip: "0.0.0.0"
      port: 9091
    metrics:
      http_status:
        extra_labels:
          - upstream_addr: $upstream_addr
          - upstream_status: $upstream_status
          - soap_action: $soap_action
          {{- /* instance_name is NOT added here. The plugin can only attach
                 extra_labels to http_status, which would leave latency,
                 bandwidth and the nginx gauges unlabelled; it is stamped on
                 every series at scrape time by the ServiceMonitor's relabeling
                 instead (frankgateway-servicemonitor.yaml). */}}
# nginx does not pass the process environment to workers unless each variable
# is declared here, so the OpenBao Lua would see nil for all of them. Only the
# NAMES appear in this config; the token VALUE reaches the container from a
# Secret and never lands in etcd, git or a ConfigMap.
nginx_config:
  {{- if $fg.accessLog.jsonFormat }}
  # Structured JSON access logs: one object per request, json-escaped, so
  # Loki/Alloy pipelines can filter on fields (host/uri/status/upstream/
  # latency) instead of regex-parsing the combined format. instance_name
  # identifies which traffic class served the request once the gateway is
  # split, so one Loki query can separate inway from outway from internal.
  http:
    access_log_format_escape: json
    access_log_format: '{"time":"$time_iso8601","instance_name":"{{ .name }}","client":"$remote_addr","method":"$request_method","host":"$host","uri":"$uri","query":"$args","status":$status,"bytes_sent":$body_bytes_sent,"request_time":$request_time,"upstream_addr":"$upstream_addr","upstream_status":"$upstream_status","upstream_response_time":"$upstream_response_time","request_id":"$request_id","referer":"$http_referer","user_agent":"$http_user_agent"}'
  {{- end }}
  main_configuration_snippet: |
    env OPENBAO_TOKEN;
    env OPENBAO_ADDR;
    env OPENBAO_MOUNT;
    env OPENBAO_KV;
    env OPENBAO_FAIL_MODE;
{{- end -}}

{{/*
Frank!Gateway — OpenBao address for the request-time secret fetch.

Defaults to the active (unsealed leader) Service of the OpenBao in this
release; the standby pods answer 5xx on reads, so the plain `-openbao` Service
would fail intermittently in a way that looks like a flaky secret.

Usage: {{ include "podiumd.frankgateway.openbaoAddr" (dict "root" $ "instance" $inst) }}
*/}}
{{- define "podiumd.frankgateway.openbaoAddr" -}}
{{- with .instance.openbao.addr -}}
{{- . -}}
{{- else -}}
http://{{ .root.Release.Name }}-openbao-active:8200
{{- end -}}
{{- end -}}

{{/*
Frank!Gateway — dashboard-internal credentials for one gateway instance.

Same lookup-or-generate contract as the Admin API keys. Shared by the dashboard
conf Secret, the shim nginx.conf (which posts the password server-side) and the
shim Deployment's checksum, so all three always describe the same password.

Returns YAML; consume with `fromYaml`.
*/}}
{{- define "podiumd.frankgateway.dashboardCreds" -}}
{{- $adminPassword := .instance.dashboard.adminPassword | default "" -}}
{{- $jwtSecret := "" -}}
{{- $existing := lookup "v1" "Secret" .root.Release.Namespace (printf "%s-dashboard-conf" .name) -}}
{{- if $existing -}}
{{-   if eq $adminPassword "" -}}
{{-     $adminPassword = index $existing.data "admin-password" | default "" | b64dec -}}
{{-   end -}}
{{-   $jwtSecret = index $existing.data "jwt-secret" | default "" | b64dec -}}
{{- end -}}
{{- if eq $adminPassword "" }}{{- $adminPassword = randAlphaNum 32 }}{{- end -}}
{{- if eq $jwtSecret "" }}{{- $jwtSecret = randAlphaNum 32 }}{{- end -}}
adminPassword: {{ $adminPassword | quote }}
jwtSecret: {{ $jwtSecret | quote }}
{{- end -}}

{{/*
Frank!Gateway — Keycloak OIDC client id for one instance's dashboard.

One client per instance: each dashboard has its own hostname and therefore its
own redirect URI, so they cannot share one.

Usage: {{ include "podiumd.frankgateway.oidcClientId" (dict "key" $key) }}
*/}}
{{- define "podiumd.frankgateway.oidcClientId" -}}
frankgateway-dashboard-{{ .key }}
{{- end -}}

{{/*
Frank!Gateway — shim nginx.conf for one instance's dashboard.

In a helper so the shim Deployment can checksum its own instance's config: the
annotation used to hash the whole dashboard template file, which in a split
deployment would give every shim the same checksum and restart all of them
whenever any instance changed.

Usage: {{ include "podiumd.frankgateway.shimConf"
          (dict "root" $ "instance" $fg "name" $name "adminPassword" $pw) }}
*/}}
{{- define "podiumd.frankgateway.shimConf" -}}
{{- $dash := .instance.dashboard -}}
worker_processes 1;
pid /tmp/nginx.pid;
events { worker_connections 1024; }
http {
  # The dashboard's gzip is disabled upstream (Accept-Encoding stripped so
  # sub_filter can rewrite the HTML), so re-compress here — otherwise the
  # multi-MB SPA JS/CSS bundles are served uncompressed and the page is slow.
  gzip on;
  gzip_comp_level 5;
  gzip_min_length 1024;
  gzip_proxied any;
  gzip_vary on;
  gzip_types text/plain text/css application/json application/javascript
             text/javascript application/x-javascript image/svg+xml
             application/font-woff font/woff2;
  # Resolve the dashboard Service at request time (kube-dns), via a variable
  # in proxy_pass — otherwise nginx caches the pod IP at startup and returns
  # 502 after the dashboard pod restarts (new IP).
  resolver {{ $dash.auth.dnsResolver }} valid=10s ipv6=off;
  server {
    listen 8080;
    set $dashboard "{{ .name }}-dashboard.{{ .root.Release.Namespace }}.svc.cluster.local";
    # Server-side login to the dashboard: the admin credential is injected
    # here and never reaches the browser. Returns {data:{token}}.
    location = /__fglogin {
      rewrite ^ /apisix/admin/user/login break;
      proxy_pass http://$dashboard:9000;
      proxy_set_header Content-Type "application/json";
      proxy_pass_request_body off;
      proxy_set_body '{"username":"admin","password":"{{ .adminPassword }}"}';
    }
    location / {
      proxy_pass http://$dashboard:9000;
      proxy_set_header Host $host;
      # disable upstream gzip so sub_filter can rewrite the SPA shell
      proxy_set_header Accept-Encoding "";
      sub_filter_once on;
      sub_filter '</head>' '<script>if(!localStorage.getItem("token")){fetch("/__fglogin",{method:"POST"}).then(function(r){return r.json()}).then(function(d){if(d&&d.data&&d.data.token){localStorage.setItem("token",d.data.token);location.reload()}})}</script></head>';
    }
  }
}
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
{{/*
Overrides of two subchart chart-label helpers.

create-required-catalogi.yaml and create-required-objecttypen.yaml are podiumd
templates, but they label their objects with the openzaak / objecttypen
subcharts' label helpers. Those helpers read `.Chart`, and when called from a
podiumd template that is PODIUMD's Chart — so they build the label from
podiumd's version, not the subchart's.

Both carry the stock helm scaffold's truncation, which trims only a trailing
"-" after cutting to 63 characters. A long snapshot version whose cut lands on
a "." therefore produces an invalid label and fails the release at admission.
Fixing podiumd.chart alone does not help these two files.

Helm template definitions are global and the parent chart is loaded after its
dependencies, so redefining the names here replaces the subchart versions
everywhere, including inside the subcharts' own templates. That is safe: the
only behavioural difference is stripping trailing "." and "_" as well as "-",
which can only occur when the truncation actually cuts something off. The
subcharts' own versions are short, so their rendered labels are unchanged —
verified by the byte-identical default-render check.
*/}}
{{- define "openzaak.chart" -}}
{{- $c := printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 -}}
{{- regexReplaceAll "[^a-zA-Z0-9]+$" $c "" -}}
{{- end }}

{{- define "objecttypen.chart" -}}
{{- $c := printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 -}}
{{- regexReplaceAll "[^a-zA-Z0-9]+$" $c "" -}}
{{- end }}
