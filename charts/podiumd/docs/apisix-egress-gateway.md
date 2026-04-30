# APISIX as an outbound (egress) API gateway

> Tracks parent story [IN-1866 — PodiumD 4.7: Api Gateway (APISIX)](https://dimpact.atlassian.net/browse/IN-1866).

## Why egress, not ingress

In PodiumD 4.7 APISIX is wired in as an **outbound** API gateway. PodiumD applications (e.g. OpenZaak, OpenKlant, OMC) send outbound API calls to the APISIX in-cluster service rather than calling upstream third-party APIs directly.

This gives us a single point to:

- enforce outbound policy (rate limits, allow-lists, request shaping)
- observe outbound traffic (Prometheus metrics, access logs)
- terminate / re-originate TLS, including future mTLS to upstream APIs ([IN-1922](https://dimpact.atlassian.net/browse/IN-1922))
- keep PodiumD APIs internal-only ([IN-1921](https://dimpact.atlassian.net/browse/IN-1921))

There is **no ingress concern** — APISIX does not front any PodiumD application from the public internet. The existing ingress paths in `values.yaml` are unchanged.

## Why no operator

There is no official Apache APISIX Kubernetes operator. The community feature request ([apache/apisix#10546](https://github.com/apache/apisix/issues/10546)) was closed as not planned. The `apisix-ingress-controller` exists but is a routing-CRD controller (not a lifecycle operator) and is unnecessary for egress-only use. We deploy the gateway directly via the upstream [`apisix/apisix`](https://github.com/apache/apisix-helm-chart) Helm chart.

## Chart wiring

The umbrella chart pins a single sub-chart:

```yaml
# charts/podiumd/Chart.yaml
- name: apisix
  version: 2.14.0       # appVersion 3.16.0
  repository: "@apisix" # https://apache.github.io/apisix-helm-chart
  condition: apisix.enabled
```

The operator GUI ships **inside** this chart (see "Dashboard" below), so no sibling `apisix-dashboard` dependency is needed.

Repo alias `@apisix` is registered by:

- `charts/podiumd/scripts/add-helm-repos.sh` (local development)
- `.github/workflows/podiumd-test-podiumd-helm-chart-changes.yaml` (PR validation)
- `.github/workflows/release-snapshot.yaml` (snapshot releases)

## Default values

The `apisix:` block in `charts/podiumd/values.yaml` ships with the gateway **disabled**. Opt in per environment by overriding:

```yaml
apisix:
  enabled: true
```

The defaults turn off the bundled ingress controller, pin the gateway data-plane service to `ClusterIP`, and keep the upstream chart's defaults for the Admin API + embedded Dashboard (also `ClusterIP`, also `enable_admin_ui: true`).

## Dashboard: embedded in APISIX 3.16+

From APISIX **3.16** onwards (2026-04-08) the gateway ships an **embedded Dashboard UI** served at the Admin API port:

```
http://<apisix-admin-service>:9180/ui/
```

The upstream `apisix/apisix` chart 2.14.0 (appVersion 3.16.0) enables it by default (`apisix.admin.enable_admin_ui: true`). No separate Helm chart is required and the deprecated `apache/apisix-dashboard` project is not needed.

Source of truth: [`apache/apisix` 3.16.0 dashboard docs](https://github.com/apache/apisix/blob/3.16.0/docs/en/latest/dashboard.md):

> "APISIX has a built-in Dashboard UI that is enabled by default, allowing users to easily configure routes, plugins, upstream services, and more through a graphical interface."

### Default credentials — must be overridden before production

The upstream chart ships well-known public defaults for the Admin API keys:

| Role   | Default key                          |
|--------|--------------------------------------|
| admin  | `edd1c9f034335f136f87ad84b625c8f1`   |
| viewer | `4054f7cf07e344346cd3f287985e76a2`   |

These keys are **publicly documented** by APISIX and let anyone with network access perform full CRUD on the gateway. The chart supports pulling both keys from a Kubernetes Secret instead:

```yaml
apisix:
  admin:
    credentials:
      secretName: apisix-admin-credentials
```

The Secret must contain keys `admin` and `viewer`.

### Open TODOs (tracked under IN-1866)

1. **Validate APISIX end-to-end** with the embedded Dashboard reachable from inside the cluster (port-forward + login with the default keys). Confirms the chart wiring is correct before any auth work begins.
2. **Replace the default Admin API keys** with values backed by Azure Key Vault, exposed via the existing CSI driver pattern as a Kubernetes Secret named `apisix-admin-credentials`. Wire `apisix.admin.credentials.secretName` to that Secret.
3. **Front the Admin API + Dashboard with an authenticating reverse proxy** — the embedded UI has no built-in user auth beyond the Admin API key. Recommended: oauth2-proxy + Keycloak (already deployed in PodiumD via the Keycloak operator) so operator login is gated by the same identity provider used elsewhere. Do **not** expose the Admin service via an Ingress without this proxy.
4. Once the proxy is in place, **widen `apisix.admin.allow.ipList`** to the cluster pod CIDR so the proxy pod can reach the admin port — keep it as narrow as possible.

### Access control summary

The Admin API + Dashboard service is `ClusterIP` and (until the TODOs above land) only reachable from inside the APISIX pod itself, because the upstream chart's default `allow.ipList` is `127.0.0.1/24`. To validate the GUI in the meantime, use:

```shell
kubectl -n <namespace> port-forward svc/apisix-admin 9180:9180
# then open http://localhost:9180/ui/
```

## Configuring egress routes

Route, upstream, and plugin configuration belongs under `apisix.apisixYaml`. The schema is the upstream APISIX standalone-mode schema — see the [APISIX standalone deployment docs](https://apisix.apache.org/docs/apisix/deployment-modes/#standalone) for the authoritative reference.

A minimal egress-route example (sketch — adapt to your upstream API and plugins):

```yaml
apisix:
  enabled: true
  apisix:
    deployment:
      role: traditional
      role_traditional:
        config_provider: yaml
  apisixYaml:
    upstreams:
      - id: brp-haalcentraal
        scheme: https
        pass_host: node
        nodes:
          "lab.api.mijniconnect.nl:443": 1
    routes:
      - uri: /haalcentraal/api/brp/*
        upstream_id: brp-haalcentraal
        plugins:
          prometheus: {}
    #END
```

PodiumD apps that need to reach `https://lab.api.mijniconnect.nl/haalcentraal/api/brp/...` would then point their outbound base URL at `http://apisix.<namespace>.svc.cluster.local/haalcentraal/api/brp/...`.

## Observability and operations

The default chart ships with the `prometheus` plugin available — the existing `monitoring-logging` chart can scrape APISIX metrics via a `ServiceMonitor` (tracked under [IN-1874](https://dimpact.atlassian.net/browse/IN-1874)). Backup / restore of route config is trivial because all configuration lives in this values file ([IN-1873](https://dimpact.atlassian.net/browse/IN-1873)). Staged deploy considerations are tracked under [IN-1872](https://dimpact.atlassian.net/browse/IN-1872), and the operations runbook for DevOps staff under [IN-1871](https://dimpact.atlassian.net/browse/IN-1871).

## References

- Upstream chart: <https://github.com/apache/apisix-helm-chart>
- APISIX docs: <https://apisix.apache.org/docs/apisix/getting-started/>
- Standalone mode: <https://apisix.apache.org/docs/apisix/deployment-modes/#standalone>
- Full values reference: `helm show values apisix/apisix --version 2.14.0`
