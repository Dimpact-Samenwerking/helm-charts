# Upgrade guide: monitoring-logging 1.0.18 → 1.0.19

## Summary of changes

Subchart dependency bumps (`Chart.yaml`), picked after individually testing
every available bump with `helm dependency update` + `helm template` diffs
against a baseline render:

- `prometheus-pushgateway`: 3.6.0 → 3.8.0.
- `alloy`: 1.6.2 → 1.12.1.
- `kube-prometheus-stack`: 83.0.0 → 90.0.0.

`loki` (6.55.0, latest 7.3.0) and `opentelemetry-collector` (0.147.1, latest
0.172.1) were deliberately **not** bumped here — see "Deferred" below.

## Why

None of `prometheus-pushgateway`, `alloy`, or `kube-prometheus-stack` change
any image this chart pins explicitly, so the render diff is template/CRD-only.

- `prometheus-pushgateway` 3.8.0: only chart-version labels and a whitespace
  no-op change. No functional diff.
- `alloy` 1.12.1: DaemonSet pod template gains a `K8S_NODE_NAME` env var,
  explicit `imagePullPolicy`, and a hardened `securityContext` (drop `ALL`
  capabilities, `runAsNonRoot`, seccomp `RuntimeDefault`). Pure improvement,
  nothing removed or renamed.
- `kube-prometheus-stack` 90.0.0: bundled prometheus-operator CRDs move from
  the v0.90.1 to v0.93.1 schema (additive fields only — same `group`
  (`monitoring.coreos.com`) and `version` (`v1`) for every CRD, nothing
  removed/renamed). Built-in alerting rules got minor content updates
  (renamed a couple of alert summaries, added `runbook_url` annotations).
  Prometheus's own self-scrape auth moved from the automounted
  `bearerTokenFile` to a dedicated long-lived token `Secret` — new resource,
  same effect. All images we pin explicitly (prometheus, prometheus-operator,
  admission-webhook, kube-webhook-certgen, config-reloader, node-exporter,
  kube-state-metrics) are unaffected since we override every one of them.

## Action required

**`kube-prometheus-stack`'s CRDs must be applied manually before/with this
upgrade** — `helm upgrade` never touches CRDs already installed on a cluster.
Apply the updated CRDs from the vendored chart before rolling out this
release:

```bash
for f in charts/kube-prometheus-stack-90.0.0/charts/crds/crds/*.yaml; do
  kubectl apply -f "$f"
done
```

(Extract from `charts/monitoring-logging/charts/kube-prometheus-stack-90.0.0.tgz`
after `helm dependency update`, or pull the same files from
`https://github.com/prometheus-operator/prometheus-operator/tree/v0.93.1/example/prometheus-operator-crd`.)

No other action required — `alloy` and `prometheus-pushgateway` bumps are
drop-in.

## Traefik PodMonitor: optional relabeling

`traefikMonitor` gains `relabelings` and `metricRelabelings`, passed through to the
PodMonitor's `podMetricsEndpoints`. Use them to add labels to the Traefik metrics,
for example the backend namespace taken from Traefik's `service` label, instead of
deploying a second monitor on Traefik (which stores every series twice). See
`docs/prometheus-scraping.md` § Traefik.

No action required: both default to `[]`, which renders the PodMonitor exactly as
before.

## Grafana sends HSTS

Grafana now sends `Strict-Transport-Security: max-age=31536000` (IN-3162):
`grafana."grafana.ini".security.strict_transport_security: true` with
`strict_transport_security_max_age_seconds: "31536000"`. The value is quoted on
purpose: unquoted, the Grafana chart renders it as `3.1536e+07`.

No action required. An environment whose edge already sets HSTS keeps working:
the edge's value replaces Grafana's.

## node-exporter: no distroless image

`kube-prometheus-stack` 90.0.0 turns on node-exporter's distroless image, which
appends `-distroless` to the tag. The pinned `v1.9.1` has no distroless variant
(those start at v1.11.0), so without a fix node-exporter cannot pull its image
(`ImagePullBackOff` on every node). The chart sets
`kube-prometheus-stack.prometheus-node-exporter.image.distroless: false`.

No action required. When you raise the node-exporter tag to v1.11.0 or later, you
can turn distroless back on.

## Resource requests for sidecars and Loki components

These containers had no CPU or memory requests, so the scheduler reserved nothing
for them:

| Values key | Container(s) | Requests |
|---|---|---|
| `grafana.sidecar.resources` | `grafana-sc-dashboard`, `grafana-sc-datasources` | 10m / 96Mi |
| `loki.sidecar.resources` | `loki-sc-rules` | 10m / 96Mi |
| `loki.memcachedExporter.resources` | the exporter next to chunks-cache and results-cache | 10m / 32Mi |
| `loki.compactor.resources` | compactor (Distributed mode) | 50m / 128Mi |
| `loki.ruler.resources` | ruler (Distributed mode) | 20m / 128Mi |

The sidecar values follow the use measured on QA (about 70Mi for each Grafana
sidecar, 82Mi for `loki-sc-rules`). Only requests are set, no limits.

No action required. The pods restart once with the new requests. An environment
that sets its own `resources` for these keys keeps them; Helm merges the maps, so
an environment that sets only `limits` gets these requests as well.

## Traefik PodMonitor off by default

`traefikMonitor.enabled` now defaults to `false`. The PodiumD edge is NGINX
Gateway Fabric, so the PodMonitor found no Traefik pods and left Prometheus
with an empty scrape pool (`podMonitor/<namespace>/<release>-traefik`). The
`kubernetes-pods` job already scrapes NGF through its pod annotations (port
9113). See `docs/prometheus-scraping.md` § NGINX Gateway Fabric.

Action for an environment that still runs Traefik at the edge: set
`traefikMonitor.enabled: true`, or the Traefik metrics and the Traefik
dashboard stop receiving data.

## Deferred (tracked as backlog items, not folded in here)

- **`loki` 6.55.0 → 7.3.0**: the chart's default MinIO images silently
  change from `quay.io/minio/{minio,mc}` to `docker.io/pgsty/{minio,mc}` (a
  third-party fork, since MinIO Inc. restricted free image access). This
  chart currently only pins `tag` for `loki.minio.image`/`mcImage`, not
  `registry`/`repository`, so the bump would silently start pulling from an
  unvetted registry. Needs triage on which MinIO image source to standardize
  on before bumping.
- **`opentelemetry-collector` 0.147.1 → 0.172.1**: the chart's
  `service.telemetry.metrics` config-building helper that turned our
  `resource:` map into `with_resource_constant_labels` (host.name,
  k8s.namespace.name, k8s.node.name, etc. as labels on the collector's own
  self-metrics) was removed upstream with no automatic replacement — those
  labels silently disappear from the collector's self-monitoring metrics.
  Low blast radius (only the collector's own health metrics, not the
  log/metric/trace pipeline itself), but needs an explicit values.yaml fix to
  preserve parity before bumping.
- **Verify this chart with verify-podiumd**: the podiumd chart's verify script
  does not check this chart yet. Assessment, plan and effort (about 1.5 to 2.5
  days) in [verify-tooling-assessment.md](verify-tooling-assessment.md).
