# Upgrade guide: PodiumD 4.6.5 → 4.6.6

## Changes

### `apiproxy.nginxCertsSecret` default changed to empty

`apiproxy.nginxCertsSecret` previously defaulted to `"api-proxy-certs"`. That secret is **not** present in every environment (only some clusters provision it for upstream mTLS to BAG/BRP/KVK), so the implicit default produced a missing-secret error or, where the secret happened to exist with a different name, a silently misconfigured proxy.

In 4.6.6 the default is `""` (empty). When empty:

- The cert volume / `/etc/nginx/certs` mount is omitted.
- `proxy_ssl_certificate` / `proxy_ssl_certificate_key` directives are not rendered (no client cert sent upstream).
- `apiproxy.locations.commonSettings.sslVerify` (still `""` = auto-derive) resolves to `"off"`, so upstream server certs are **not** validated.

#### Action required

If your environment **does** use upstream mTLS via the api-proxy and the secret is provisioned in the `podiumd` namespace, pin the value explicitly in your gemeente `podiumd.yml` **before** running `helm upgrade`:

```yaml
apiproxy:
  enabled: true
  nginxCertsSecret: api-proxy-certs   # or whatever name the secret has in your cluster
```

To check the current setting and whether the secret exists:

```bash
helm --kube-context "$CTX" get values podiumd -n podiumd -o yaml \
  | yq '.apiproxy.nginxCertsSecret // "<unset — will use new chart default>"'

kubectl --context "$CTX" -n podiumd get secret api-proxy-certs --ignore-not-found
```

If `apiproxy.enabled` is `false` (most non-DIMP gemeentes), no action is needed.

### `apiproxy.sslVerifyDepth` — global default with per-location overrides

The earlier 4.6.6 work introduced per-location `sslVerifyDepth` (`apiproxy.locations.bag.sslVerifyDepth`, `…brp.sslVerifyDepth`, etc.) defaulting to `"5"`. That has been reworked: there is now a single global default at `apiproxy.sslVerifyDepth` (default `6`), and per-location overrides are still supported but no longer required:

```yaml
apiproxy:
  sslVerifyDepth: 6              # global default
  locations:
    bag:
      sslVerifyDepth: 10         # override only for BAG
    brp:
      sslVerifyDepth: 4          # override only for BRP
```

Resolution order per upstream: location override → global → chart default of `6`. The dead per-location `sslVerifyDepth: "5"` lines that the earlier commit left in `values.yaml` have been removed. nginx ignores `proxy_ssl_verify_depth` when `proxy_ssl_verify` is `off`, so this only affects environments that do mount mTLS certs.

The depth bump from nginx's default of `1` to `6` matters for cross-signed government API chains (BAG/BRP/KVK gateways occasionally chain through extra intermediates). No action required if you don't need a different depth.
