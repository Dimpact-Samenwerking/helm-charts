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
  repository: "@apisix" # https://charts.apiseven.com
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

### Admin API credentials — auto-generated, no public defaults

The upstream chart ships well-known public defaults for the Admin API keys (`edd1c9f0…` / `4054f7cf…`) which let anyone with network access perform full CRUD on the gateway. The umbrella chart **replaces these on first install** with random 32-character values:

- `charts/podiumd/templates/apisix-admin-credentials.yaml` renders a Secret named `apisix-admin-credentials` with keys `admin` and `viewer`, generated via `randAlphaNum 32`.
- `lookup` keeps the values stable across upgrades.
- `values.yaml` already wires `apisix.admin.credentials.secretName: apisix-admin-credentials`, so the upstream chart picks them up.

To use Azure Key Vault via the CSI driver instead of the auto-generated Secret, override `apisix.admin.credentials.secretName` to point at your own Secret containing the same `admin` and `viewer` keys. The umbrella template skips rendering when the default name is overridden.

### OIDC-protected dashboard access

Operator access to the embedded Admin Dashboard is gated by Keycloak via the [APISIX `openid-connect` plugin](https://apisix.apache.org/docs/apisix/plugins/openid-connect/). The route is shipped in `values.yaml` under `apisix.apisix.deployment.standalone.config` and proxies `/ui/*` on the data-plane port (80) to `127.0.0.1:9180/ui/`. Direct access to `:9180/ui/` is in-pod only (`allow.ipList` defaults to `127.0.0.1/24`).

> **Note on nesting:** the upstream `apisix/apisix` chart 2.14.0 namespaces its own settings under a top-level `apisix:` key (`admin`, `deployment`, `router`, …). The umbrella path is therefore `apisix.apisix.<key>` — top-level settings like `service`, `extraEnvVars`, `etcd` are at `apisix.<key>`.

#### Tenant setup

1. **Create a Keycloak client** in your realm:

   | Setting              | Value |
   |----------------------|-------|
   | Client ID            | `apisix-dashboard` |
   | Access Type          | `confidential` |
   | Standard Flow        | enabled |
   | Valid Redirect URIs  | `http://apisix-gateway.<namespace>.svc/ui/*` |
   | Web Origins          | `+` |

2. **Create the client-secret Secret** in the same namespace as the apisix release:

   ```shell
   kubectl -n <namespace> create secret generic apisix-oidc-client-secret \
     --from-literal=clientSecret='<client-secret-from-keycloak>'
   ```

   Or, recommended, sync it from Azure Key Vault using the existing CSI driver pattern.

3. **Set the realm discovery URL** in your tenant `podiumd.yml`. Because `apisix.apisix.deployment.standalone.config` is a YAML-string field, override the whole block:

   ```yaml
   apisix:
     enabled: true
     apisix:
       deployment:
         mode: standalone
         standalone:
           config: |
             routes:
               - id: apisix-dashboard-oidc
                 uri: /ui/*
                 upstream:
                   type: roundrobin
                   nodes:
                     "127.0.0.1:9180": 1
                 plugins:
                   openid-connect:
                     client_id: "apisix-dashboard"
                     client_secret: "$env://OIDC_CLIENT_SECRET"
                     discovery: "https://<your-keycloak>/realms/podiumd/.well-known/openid-configuration"
                     scope: "openid profile email"
                     bearer_only: false
                     realm: "podiumd"
                     introspection_endpoint_auth_method: "client_secret_basic"
                     ssl_verify: true
   ```

   The `client_secret: "$env://OIDC_CLIENT_SECRET"` reference is resolved at runtime by APISIX 3.x from the env var injected via `apisix.extraEnvVars` — never embed the literal secret in values.

#### Disabling OIDC

To remove the OIDC route entirely (e.g. ephemeral dev clusters where port-forward is sufficient), override `apisix.apisix.deployment.standalone.config` with an empty rule set:

```yaml
apisix:
  apisix:
    deployment:
      standalone:
        config: |
          routes: []
```

The dashboard is then reachable only via:

```shell
kubectl -n <namespace> port-forward svc/apisix-admin 9180:9180
# then open http://localhost:9180/ui/
```

### Access control summary

| Surface | Reachability | Auth |
|---------|--------------|------|
| `apisix-admin:9180/ui/` (direct) | In-pod only (`allow.ipList: 127.0.0.1/24`) | Admin API key (auto-generated) |
| `apisix-gateway:80/ui/` (data plane) | Cluster-wide ClusterIP | Keycloak OIDC (when `apisix-oidc-client-secret` is provisioned) |
| `apisix-gateway:80/<egress-route>` | Cluster-wide ClusterIP | Per-route plugins (see "Configuring egress routes") |

## Configuring egress routes

Route, upstream, and plugin configuration belongs in the YAML string at `apisix.apisix.deployment.standalone.config`. The schema is the upstream APISIX standalone-mode schema — see the [APISIX standalone deployment docs](https://apisix.apache.org/docs/apisix/deployment-modes/#standalone) for the authoritative reference.

A minimal egress-route example (sketch — adapt to your upstream API and plugins). Add to the same `routes:` list as the OIDC dashboard route:

```yaml
apisix:
  enabled: true
  apisix:
    deployment:
      mode: standalone
      standalone:
        config: |
          routes:
            - id: apisix-dashboard-oidc
              # …OIDC route from the section above…
            - id: brp-egress
              uri: /haalcentraal/api/brp/*
              upstream_id: brp-haalcentraal
              plugins:
                prometheus: {}
          upstreams:
            - id: brp-haalcentraal
              scheme: https
              pass_host: node
              nodes:
                "lab.api.mijniconnect.nl:443": 1
```

PodiumD apps that need to reach `https://lab.api.mijniconnect.nl/haalcentraal/api/brp/...` would then point their outbound base URL at `http://apisix.<namespace>.svc.cluster.local/haalcentraal/api/brp/...`.

## Observability and operations

The default chart ships with the `prometheus` plugin available — the existing `monitoring-logging` chart can scrape APISIX metrics via a `ServiceMonitor` (tracked under [IN-1874](https://dimpact.atlassian.net/browse/IN-1874)). Backup / restore of route config is trivial because all configuration lives in this values file ([IN-1873](https://dimpact.atlassian.net/browse/IN-1873)). Staged deploy considerations are tracked under [IN-1872](https://dimpact.atlassian.net/browse/IN-1872), and the operations runbook for DevOps staff under [IN-1871](https://dimpact.atlassian.net/browse/IN-1871).

## References

- Upstream chart: <https://github.com/apache/apisix-helm-chart>
- APISIX docs: <https://apisix.apache.org/docs/apisix/getting-started/>
- Standalone mode: <https://apisix.apache.org/docs/apisix/deployment-modes/#standalone>
- Full values reference: `helm show values apisix/apisix --version 2.14.0`
