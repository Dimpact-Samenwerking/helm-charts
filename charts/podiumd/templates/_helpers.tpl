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

The result is memoised for the duration of the render, in a dict hung off
.Values. Sharing the helper is not enough on its own: each call ran its own
`lookup` + `randAlphaNum` fallback, so on a FRESH install — where the lookup
finds nothing — the Secret and the checksum were computed from different
random values, and the next no-op `helm upgrade` rolled every pod for nothing.
Helm validates values against the schema before rendering, so the extra key
affects this pass and nothing else.

Returns YAML; consume with `fromYaml`:
  {{- $creds := include "podiumd.frankgateway.adminCreds"
        (dict "root" $ "instance" $inst "name" $name) | fromYaml }}
*/}}
{{- define "podiumd.frankgateway.adminCreds" -}}
{{- if not (hasKey .root.Values "__frankgatewayCredsAdmin") -}}{{- $_ := set .root.Values "__frankgatewayCredsAdmin" dict -}}{{- end -}}
{{- $cache := index .root.Values "__frankgatewayCredsAdmin" -}}
{{- if not (hasKey $cache .name) -}}
{{-   $admin := .instance.admin.adminKey | default "" -}}
{{-   $viewer := .instance.admin.viewerKey | default "" -}}
{{-   $existing := lookup "v1" "Secret" .root.Release.Namespace (printf "%s-admin-credentials" .name) -}}
{{-   if and (eq $admin "") $existing -}}
{{-     $admin = index $existing.data "admin" | default "" | b64dec -}}
{{-   end -}}
{{-   if and (eq $viewer "") $existing -}}
{{-     $viewer = index $existing.data "viewer" | default "" | b64dec -}}
{{-   end -}}
{{-   if eq $admin "" }}{{- $admin = randAlphaNum 32 }}{{- end -}}
{{-   if eq $viewer "" }}{{- $viewer = randAlphaNum 32 }}{{- end -}}
{{-   $_ := set $cache .name (dict "admin" $admin "viewer" $viewer) -}}
{{- end -}}
{{- $c := get $cache .name -}}
admin: {{ $c.admin | quote }}
viewer: {{ $c.viewer | quote }}
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
    access_log_format: '{"time":"$time_iso8601","instance_name":"{{ .name }}","client":"$remote_addr","method":"$request_method","host":"$host","uri":"$uri","query":"$args","status":$status,"bytes_sent":$body_bytes_sent,"request_time":$request_time,"upstream_addr":"$upstream_addr","upstream_status":"$upstream_status","upstream_response_time":"$upstream_response_time","request_id":"$request_id","referer":"$http_referer","user_agent":"$http_user_agent","consumer":"$http_x_consumer_username"}'
  {{- end }}
  main_configuration_snippet: |
    env OPENBAO_TOKEN;
    env OPENBAO_ADDR;
    env OPENBAO_MOUNT;
    env OPENBAO_KV;
    env OPENBAO_FAIL_MODE;
{{- end -}}

{{/*
Frank!Gateway — DNS names the data-plane certificate must cover.

The in-cluster Service names are always included, because that is what a
re-encrypting front door connects to and what its BackendTLSPolicy validates
against. Anything else (a public hostname on this hop) comes from
tls.certManager.extraDnsNames.

Returns a YAML list.

Usage: {{ include "podiumd.frankgateway.certDnsNames" (dict "root" $root "instance" $fg "name" $name) }}
*/}}
{{- define "podiumd.frankgateway.certDnsNames" -}}
{{- $ns := .root.Release.Namespace -}}
- {{ .name | quote }}
- {{ printf "%s.%s.svc" .name $ns | quote }}
- {{ printf "%s.%s.svc.cluster.local" .name $ns | quote }}
{{- range .instance.tls.certManager.extraDnsNames }}
- {{ . | quote }}
{{- end }}
{{- end -}}

{{/*
Frank!Gateway — issuerRef for the data-plane Certificate.

An explicitly named issuer wins. Otherwise, when the chart renders the
OpenBao-backed Issuer, point at that one — so enabling it is a single flag
rather than a flag plus a name that has to match.

Returns YAML (name/kind/group).

Usage: {{ include "podiumd.frankgateway.certIssuerRef" (dict "instance" $fg) }}
*/}}
{{- define "podiumd.frankgateway.certIssuerRef" -}}
{{- $cm := .instance.tls.certManager -}}
{{- if $cm.issuerRef.name -}}
name: {{ $cm.issuerRef.name }}
kind: {{ $cm.issuerRef.kind }}
group: {{ $cm.issuerRef.group }}
{{- else -}}
name: frankgateway-openbao
kind: Issuer
group: cert-manager.io
{{- end -}}
{{- end -}}

{{/*
Frank!Gateway — name of the Secret holding the data-plane certificate.

Explicit sslSync.secretName wins; otherwise the cert-manager Secret when that
is enabled; otherwise <instance>-tls, supplied out-of-band.

Usage: {{ include "podiumd.frankgateway.tlsSecretName" (dict "instance" $fg "name" $name) }}
*/}}
{{- define "podiumd.frankgateway.tlsSecretName" -}}
{{- $tls := .instance.tls -}}
{{- if $tls.sslSync.secretName -}}
{{- $tls.sslSync.secretName -}}
{{- else if $tls.certManager.secretName -}}
{{- $tls.certManager.secretName -}}
{{- else -}}
{{ .name }}-tls
{{- end -}}
{{- end -}}

{{/*
Frank!Gateway — the sh that PUTs the data-plane certificate into etcd as an
APISIX SSL object.

Shared verbatim by the deploy-time routes Job and the renewal CronJob, so the
two can never drift into disagreeing about what "the certificate is installed"
means.

Usage: {{ include "podiumd.frankgateway.sslSyncScript" (dict "root" $root "instance" $fg "name" $name) }}
*/}}
{{- define "podiumd.frankgateway.sslSyncScript" -}}
{{- $fg := .instance -}}
{{- $name := .name -}}
{{- $snis := $fg.tls.sslSync.snis -}}
{{- if not $snis -}}
{{- $snis = include "podiumd.frankgateway.certDnsNames" (dict "root" .root "instance" $fg "name" $name) | fromYamlArray -}}
{{- end -}}
set -eu
CRT=/tls/tls.crt
KEY=/tls/tls.key

# The Secret is mounted optional: on a first install cert-manager may not have
# issued yet, and an environment supplying its own certificate may not have
# created it. Absent material is not a failure — the next run picks it up.
if [ ! -s "${CRT}" ] || [ ! -s "${KEY}" ]; then
  echo "ssl-sync: no certificate material at /tls, nothing to do"
  exit 0
fi

{{ include "podiumd.frankgateway.adminWait" (dict "name" $name) }}

# PEM -> JSON string: the only character needing escaping is the newline, since
# PEM is base64 plus dashes. Nothing is echoed — the private key must not reach
# a pod log.
cert=$(awk '{printf "%s\\n", $0}' "${CRT}")
key=$(awk '{printf "%s\\n", $0}' "${KEY}")
umask 077
printf '{"cert":"%s","key":"%s","snis":%s}' "${cert}" "${key}" '{{ $snis | toJson }}' > /tmp/ssl.json

code=$(curl -s -o /dev/null -w "%{http_code}" -X PUT \
  "http://{{ $name }}:9180/apisix/admin/ssls/{{ $name }}" \
  -H "X-API-KEY: ${ADMIN_KEY}" -H "Content-Type: application/json" \
  --data @/tmp/ssl.json)
rm -f /tmp/ssl.json
echo "ssl-sync: ssls/{{ $name }} -> ${code}"
case "${code}" in 2*) exit 0 ;; *) exit 1 ;; esac
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
Frank!Gateway — the OPENBAO_* environment for everything that reads OpenBao
with the gateway's reader token: the gateway pods (request-time Lua), the seed
Job and the client-cert-sync CronJob. One definition, so no container can be
given a different mount or kv version than the gateway it serves.

The token is optional: a class that reads no secrets still starts without it,
and whatever does need it fails loudly at that point instead of the pod
failing to schedule.

Usage: {{ include "podiumd.frankgateway.openbaoEnv" (dict "root" $root "instance" $fg) | nindent 12 }}
*/}}
{{- define "podiumd.frankgateway.openbaoEnv" -}}
- name: OPENBAO_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ .instance.openbao.tokenSecret.name }}
      key: {{ .instance.openbao.tokenSecret.key }}
      optional: true
- name: OPENBAO_ADDR
  value: {{ include "podiumd.frankgateway.openbaoAddr" (dict "root" .root "instance" .instance) | quote }}
- name: OPENBAO_MOUNT
  value: {{ .instance.openbao.mount | default .root.Values.openbao.configuration.kvPath | quote }}
- name: OPENBAO_KV
  value: {{ .instance.openbao.kvVersion | quote }}
- name: OPENBAO_FAIL_MODE
  value: {{ .instance.openbao.failMode | quote }}
{{- end -}}

{{/*
Frank!Gateway — wait for one instance's Admin API. Shared by every script that
talks to it, because the gateway may still be rolling when a hook or CronJob
fires. Exits 1 after 30 x 5 s.

Usage (inside a script body): {{ include "podiumd.frankgateway.adminWait" (dict "name" $name) }}
*/}}
{{- define "podiumd.frankgateway.adminWait" -}}
i=0
until curl -s --max-time 5 -o /dev/null "http://{{ .name }}:9180/apisix/admin/routes" -H "X-API-KEY: ${ADMIN_KEY}"; do
  i=$((i+1)); [ "${i}" -ge 30 ] && { echo "{{ .name }}: admin API unreachable after ${i} attempts"; exit 1; }
  sleep 5
done
{{- end -}}

{{/*
Frank!Gateway — seed.sh for one instance: everything that has to be in etcd
before the instance can serve, PUT idempotently through the Admin API by the
post-install/post-upgrade hook Job (frankgateway-seed-job.yaml).

Order matters:
  1. client certs     — SSL objects from OpenBao; a route whose client_cert_id
                        has no object yet is rejected, so these go first
  2. routes           — from values only; zero routes is a valid state
  3. prune            — opt-in: managed-by=iac routes not in this render go
  4. prometheus rule  — per-route metrics for every route, seeded or GUI-made
  5. server cert      — the same ssl-sync the renewal CronJob runs

Route bodies hold no secret material (they reference OpenBao PATHS), so the
Admin API's answer is echoed on failure. ssl-sync has its own rules about that.

Usage: {{ include "podiumd.frankgateway.seedScript" (dict "root" $root "instance" $fg "name" $name) }}
*/}}
{{- define "podiumd.frankgateway.seedScript" -}}
{{- $fg := .instance -}}
{{- $name := .name -}}
set -u
ADMIN="http://{{ $name }}:9180/apisix/admin"
rc=0
warn=0
put() { # put <kind/id> <file>
  code=$(curl -s --max-time 20 -o /tmp/resp -w '%{http_code}' -X PUT "${ADMIN}/$1" \
    -H "X-API-KEY: ${ADMIN_KEY}" -H 'Content-Type: application/json' --data @"$2")
  case "${code}" in
    2*) echo "seed: $1 -> ${code}" ;;
    *)  echo "seed: $1 -> ${code}: $(head -c 400 /tmp/resp)"; rc=1 ;;
  esac
}
{{ include "podiumd.frankgateway.adminWait" (dict "name" $name) }}
{{- if $fg.clientCertificates }}
# Client certificates first: APISIX rejects a route whose client_cert_id has no
# SSL object. An OpenBao read that fails while a last-good object is in place
# is a warning here, not a failed deploy — the CronJob keeps retrying, and the
# gateway keeps presenting the certificate it has.
sh /scripts/client-cert-sync/sync.sh; ccrc=$?
case "${ccrc}" in 0) ;; 2) warn=1 ;; *) rc=1 ;; esac
{{- end }}
# Routes: this instance's values, one file per route id. The chart ships none,
# so no files is a valid state — the glob then stays unexpanded and the guard
# skips it, and the Job still succeeds.
n=0
for f in /seed/route-*.json; do
  [ -e "${f}" ] || continue
  id=$(basename "${f}" .json); id=${id#route-}
  put "routes/${id}" "${f}"
  n=$((n+1))
done
echo "seed: ${n} route(s) applied"
{{- if $fg.seed.prune }}
# Prune: a route carrying our label that is not in this render was removed from
# values, so remove it from etcd too. Routes without the label (made in the
# dashboard) are never touched.
want=" "
for f in /seed/route-*.json; do
  [ -e "${f}" ] || continue
  b=$(basename "${f}" .json); want="${want}${b#route-} "
done
for id in $(curl -s --max-time 20 -H "X-API-KEY: ${ADMIN_KEY}" "${ADMIN}/routes" \
            | grep -o '"key":"[^"]*/routes/[^"]*"' | sed 's#.*/routes/##; s/"$//'); do
  case "${want}" in *" ${id} "*) continue ;; esac
  curl -s --max-time 20 -H "X-API-KEY: ${ADMIN_KEY}" "${ADMIN}/routes/${id}" \
    | grep -q '"managed-by":"iac"' || continue
  code=$(curl -s --max-time 20 -o /dev/null -w '%{http_code}' -X DELETE \
    -H "X-API-KEY: ${ADMIN_KEY}" "${ADMIN}/routes/${id}")
  echo "seed: prune routes/${id} -> ${code}"
  case "${code}" in 2*) ;; *) rc=1 ;; esac
done
{{- end }}
{{- if $fg.metrics.enabled }}
# Per-route metrics: the prometheus plugin must be active on a route to emit
# route-level series. A global_rule covers every route (seeded and GUI-created)
# without touching each one.
printf '%s' '{"plugins":{"prometheus":{"prefer_name":true}}}' > /tmp/gr.json
put "global_rules/prometheus-metrics" /tmp/gr.json
{{- end }}
{{- if and $fg.tls.enabled $fg.tls.sslSync.enabled }}
# Data-plane certificate: the same script the renewal CronJob runs, so a fresh
# install serves TLS immediately instead of waiting for the first nightly tick.
# Exits 0 when no certificate material is mounted yet.
sh /scripts/ssl-sync/sync.sh || rc=1
{{- end }}
[ "${warn}" -eq 1 ] && echo "seed: WARNING one or more client certificates could not be refreshed from OpenBao; the last-good SSL objects were kept"
exit ${rc}
{{- end -}}

{{/*
Frank!Gateway — sync.sh that pulls one instance's client certificates from
OpenBao into APISIX SSL objects (type client), run by the seed hook at deploy
time and by the <instance>-client-cert-sync CronJob afterwards.

Why a job and not `$secret://`: on APISIX 3.16 a secret reference is resolved
for consumer credentials and for the server certificate on the handshake path,
but NOT for upstream.tls.client_cert/client_key nor via client_cert_id. APISIX
3.18 changes that; until Frank!Gateway ships on it, OpenBao is the source of
truth and etcd a copy that this script keeps current.

Exit codes, because the two callers must react differently:
  0  every certificate synced or unchanged
  2  an OpenBao read failed but the SSL object already exists — last-good kept
  1  hard failure: bad material, or no object to fall back on

curl and sed only (the job image has no jq). The extraction is exact for PEM:
the value contains no `"` and no `\` other than the `\n` escapes, so the
still-escaped string is embedded in the APISIX body as is. Neither the OpenBao
response nor the Admin API's GET is ever printed — both contain the private
key. Unchanged detection is by a sha256 of the cert kept as an SSL label,
because APISIX's JSON encoder may escape the PEM differently from OpenBao's.

Usage: {{ include "podiumd.frankgateway.clientCertSyncScript" (dict "root" $root "instance" $fg "name" $name) }}
*/}}
{{- define "podiumd.frankgateway.clientCertSyncScript" -}}
{{- $fg := .instance -}}
{{- $name := .name -}}
set -u
ADMIN="http://{{ $name }}:9180/apisix/admin"
if [ -z "${OPENBAO_TOKEN:-}" ]; then
  echo "client-cert-sync: OPENBAO_TOKEN is empty — is Secret {{ $fg.openbao.tokenSecret.name }} (key {{ $fg.openbao.tokenSecret.key }}) present?"
  exit 1
fi
umask 077
hard=0
soft=0
kv_url() {
  if [ "${OPENBAO_KV:-2}" = "1" ]; then
    echo "${OPENBAO_ADDR}/v1/${OPENBAO_MOUNT}/$1"
  else
    echo "${OPENBAO_ADDR}/v1/${OPENBAO_MOUNT}/data/$1"
  fi
}
# jfield <name>: the still-JSON-escaped string value of a top-level-looking key
jfield() { sed -n 's/.*"'"$1"'":"\([^"]*\)".*/\1/p' | head -n 1; }
{{ include "podiumd.frankgateway.adminWait" (dict "name" $name) }}
sync_one() { # sync_one <name> <openbaoPath>
  id="client-$1"
  code=$(curl -s --max-time 20 -o /tmp/bao.json -w '%{http_code}' \
    -H "X-Vault-Token: ${OPENBAO_TOKEN}" "$(kv_url "$2")")
  if [ "${code}" != "200" ]; then
    rm -f /tmp/bao.json
    have=$(curl -s --max-time 20 -o /dev/null -w '%{http_code}' -H "X-API-KEY: ${ADMIN_KEY}" "${ADMIN}/ssls/${id}")
    if [ "${have}" = "200" ]; then
      echo "client-cert-sync: ${id}: OpenBao $2 -> ${code}; keeping the last-good SSL object"
      return 2
    fi
    echo "client-cert-sync: ${id}: OpenBao $2 -> ${code}; no existing SSL object to keep"
    return 1
  fi
  cert=$(jfield cert < /tmp/bao.json)
  key=$(jfield key < /tmp/bao.json)
  rm -f /tmp/bao.json
  case "${cert}" in "-----BEGIN CERTIFICATE-----"*) ;; *) echo "client-cert-sync: ${id}: field cert at $2 is not a PEM certificate"; return 1 ;; esac
  case "${key}"  in "-----BEGIN "*)               ;; *) echo "client-cert-sync: ${id}: field key at $2 is not a PEM key";          return 1 ;; esac
  sum=$(printf '%s' "${cert}" | sha256sum | cut -c1-64)
  if curl -s --max-time 20 -H "X-API-KEY: ${ADMIN_KEY}" "${ADMIN}/ssls/${id}" | grep -qF -- "\"cert_sha256\":\"${sum}\""; then
    echo "client-cert-sync: ${id}: unchanged"
    return 0
  fi
  printf '{"type":"client","cert":"%s","key":"%s","labels":{"managed-by":"iac","cert_sha256":"%s"}}' "${cert}" "${key}" "${sum}" > /tmp/ssl.json
  code=$(curl -s --max-time 20 -o /dev/null -w '%{http_code}' -X PUT "${ADMIN}/ssls/${id}" \
    -H "X-API-KEY: ${ADMIN_KEY}" -H 'Content-Type: application/json' --data @/tmp/ssl.json)
  rm -f /tmp/ssl.json
  echo "client-cert-sync: ssls/${id} -> ${code}"
  case "${code}" in 2*) return 0 ;; *) return 1 ;; esac
}
{{- range $n, $c := $fg.clientCertificates }}
sync_one {{ $n | quote }} {{ $c.openbaoPath | quote }}; case $? in 1) hard=1 ;; 2) soft=1 ;; esac
{{- end }}
[ "${hard}" -eq 1 ] && exit 1
[ "${soft}" -eq 1 ] && exit 2
exit 0
{{- end -}}

{{/*
Frank!Gateway — dashboard-internal credentials for one gateway instance.

Same lookup-or-generate contract as the Admin API keys. Shared by the dashboard
conf Secret, the shim nginx.conf (which posts the password server-side) and the
shim Deployment's checksum, so all three always describe the same password.

Returns YAML; consume with `fromYaml`.
*/}}
{{- define "podiumd.frankgateway.dashboardCreds" -}}
{{- if not (hasKey .root.Values "__frankgatewayCredsDashboard") -}}{{- $_ := set .root.Values "__frankgatewayCredsDashboard" dict -}}{{- end -}}
{{- $cache := index .root.Values "__frankgatewayCredsDashboard" -}}
{{- if not (hasKey $cache .name) -}}
{{-   $adminPassword := .instance.dashboard.adminPassword | default "" -}}
{{-   $jwtSecret := "" -}}
{{-   $existing := lookup "v1" "Secret" .root.Release.Namespace (printf "%s-dashboard-conf" .name) -}}
{{-   if $existing -}}
{{-     if eq $adminPassword "" -}}
{{-       $adminPassword = index $existing.data "admin-password" | default "" | b64dec -}}
{{-     end -}}
{{-     $jwtSecret = index $existing.data "jwt-secret" | default "" | b64dec -}}
{{-   end -}}
{{-   if eq $adminPassword "" }}{{- $adminPassword = randAlphaNum 32 }}{{- end -}}
{{-   if eq $jwtSecret "" }}{{- $jwtSecret = randAlphaNum 32 }}{{- end -}}
{{-   $_ := set $cache .name (dict "adminPassword" $adminPassword "jwtSecret" $jwtSecret) -}}
{{- end -}}
{{- $c := get $cache .name -}}
adminPassword: {{ $c.adminPassword | quote }}
jwtSecret: {{ $c.jwtSecret | quote }}
{{- end -}}

{{/*
Frank!Gateway — the Keycloak OIDC client secret for one instance's dashboard.

ONE definition, used by both keycloak-podiumd-realm-secrets.yaml (which is
what Keycloak imports) and frankgateway-dashboard-auth.yaml (which is what
oauth2-proxy presents). Both used to generate their own randAlphaNum on a
fresh install — `lookup` cannot see a Secret that this same release is still
rendering — so the two sides held different secrets and the dashboard login
failed until a second upgrade made the lookup succeed.

Usage: {{ include "podiumd.frankgateway.oidcClientSecret" (dict "root" $ "clientId" $clientId) }}
*/}}
{{- define "podiumd.frankgateway.oidcClientSecret" -}}
{{- $root := .root -}}
{{- $id := .clientId -}}
{{- if not (hasKey $root.Values "__frankgatewayCredsOidc") -}}{{- $_ := set $root.Values "__frankgatewayCredsOidc" dict -}}{{- end -}}
{{- $cache := index $root.Values "__frankgatewayCredsOidc" -}}
{{- if not (hasKey $cache $id) -}}
{{-   $val := "" -}}
{{-   $existing := lookup "v1" "Secret" $root.Release.Namespace "keycloak-podiumd-realm-secrets" -}}
{{-   with $existing -}}
{{-     $val = index .data (printf "%s-oidc-secret" $id) | default "" | b64dec -}}
{{-   end -}}
{{-   if eq $val "" -}}{{- $val = randAlphaNum 32 -}}{{- end -}}
{{-   $_ := set $cache $id $val -}}
{{- end -}}
{{- get $cache $id -}}
{{- end -}}

{{/*
Frank!Gateway — traffic class of one instance.

`class` wins; otherwise the instance key, when that key is one of the three
known classes; otherwise empty, which means "unclassified".

One definition, because frankgateway-networkpolicy.yaml decides whether to
render a policy from it and validations.yaml decides whether to reject the
release from it. Held apart, the two drift with nothing in CI to notice.

Usage: {{ include "podiumd.frankgateway.class" (dict "key" $key "instance" $fg) }}
*/}}
{{- define "podiumd.frankgateway.class" -}}
{{- .instance.class | default (ternary .key "" (has .key (list "inway" "outway" "internal"))) -}}
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
Renders the PersistentVolume + PersistentVolumeClaim pair for a component's
shared ReadWriteMany storage on the Azure File CSI driver — same shape for
every component that needs it (objecten, openklant, openzaak, ...); the
component name is both the .Values key and the resource-name suffix.
Usage: {{ include "podiumd.storagePVC" (dict "component" "objecten" "context" $) }}
*/}}
{{- define "podiumd.storagePVC" -}}
{{- $component := .component -}}
{{- $ := .context -}}
{{- $values := index $.Values $component -}}
{{- if or $values.enabled (not (hasKey $values "enabled")) -}}
{{- $pvName := printf "%s-%s" $.Release.Namespace $component -}}
{{- if not (lookup "v1" "PersistentVolume" "" $pvName) }}
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: {{ $pvName }}
  labels:
    {{- include "podiumd.labels" $ | nindent 4 }}
  annotations:
    pv.kubernetes.io/provisioned-by: file.csi.azure.com
    helm.sh/resource-policy: keep
spec:
  capacity:
    storage: {{ $values.persistence.size }}
  accessModes:
    - ReadWriteMany
  persistentVolumeReclaimPolicy: Retain
  storageClassName: {{ $values.persistentVolume.storageClassName | default "podiumd-standard" }}
  csi:
    driver: file.csi.azure.com
    volumeHandle: {{ $pvName }}
    volumeAttributes:
      {{- if $.Values.persistentVolume.volumeAttributeResourceGroup }}
      resourceGroup: {{ $.Values.persistentVolume.volumeAttributeResourceGroup }}
      {{- end }}
      {{- if $.Values.persistentVolume.volumeAttributeShareName }}
      shareName: {{ $.Values.persistentVolume.volumeAttributeShareName }}
      {{- else }}
      shareName: {{ $values.persistentVolume.volumeAttributeShareName }}
      {{- end }}
    nodeStageSecretRef:
      name: {{ $.Values.persistentVolume.nodeStageSecretRefName }}
      namespace: {{ $.Values.persistentVolume.nodeStageSecretRefNamespace }}
  mountOptions:
    - dir_mode=0777
    - file_mode=0777
    - uid=1000
    - gid=1000
    - mfsymlinks
    - cache=strict
    - nosharesock
    - nobrl
{{- end }}
{{- if not (lookup "v1" "PersistentVolumeClaim" $.Release.Namespace $values.persistence.existingClaim) }}
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {{ $values.persistence.existingClaim }}
  labels:
    {{- include "podiumd.labels" $ | nindent 4 }}
  annotations:
    helm.sh/resource-policy: keep
spec:
  volumeName: {{ $pvName }}
  resources:
    requests:
      storage: {{ $values.persistence.size }}
  accessModes:
    - ReadWriteMany
  storageClassName: {{ $values.persistence.storageClassName | default "podiumd-standard" }}
{{- end }}
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
