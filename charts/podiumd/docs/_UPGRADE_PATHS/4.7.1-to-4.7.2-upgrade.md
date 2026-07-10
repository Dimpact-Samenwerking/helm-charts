# Upgrade guide: PodiumD 4.7.1 → 4.7.2

## Changes

### Keycloak 26.6.1 → 26.6.2 (security release)

Upstream Keycloak 26.6.2 ships fixes for a substantial set of CVEs,
including several account-takeover-class issues. Both the Keycloak
server image and the keycloak-operator image are bumped to `26.6.2`
with refreshed digests; the operator chart (Adfinis 1.11.4) is
unchanged.

CVEs addressed:

- CVE-2026-7504 — Redirect URI validation bypass
- CVE-2026-7507 — OIDC session fixation leading to account takeover
- CVE-2026-7571 — Access token disclosure / implicit-flow bypass via
  forged client data
- CVE-2026-37982 — Execute-actions token replay allows unauthorized
  WebAuthn credential enrollment
- CVE-2026-37979 — OIDC introspection endpoint does not enforce
  audience restriction
- CVE-2026-37978 — Cross-role PII leakage via evaluate-scopes
- CVE-2026-4630 — UMA Protection API IDOR
- CVE-2026-37981 — PII enumeration via account user lookup
- CVE-2026-33871 — HTTP/2 CONTINUATION frame flood DoS
- CVE-2026-33870 — HTTP request smuggling
- CVE-2026-4628 — UMA broken access control
- CVE-2026-37980 — Stored XSS
- Bouncy Castle cryptographic fixes

See <https://www.keycloak.org/2026/05/keycloak-2662-released>.

#### Action required

No values-file changes required for gemeenten — the chart bumps the
image tag and digest centrally. The ACR mirror must mirror the new
`quay.io/keycloak/keycloak:26.6.2` and `keycloak-operator:26.6.2`
tags + digests (see `docs/images/images-4.7.2.yaml`) before rolling
out 4.7.2 to a cluster.

### nginx-unprivileged 1.30.0 → 1.30.2 (security release)

All nginx sidecars and the apiproxy now pin
`nginxinc/nginx-unprivileged:1.30.2`. The 1.30.x stable line gained
two security fixes since 4.7.1 was cut:

- CVE-2026-42945 — "nginx Rift", critical RCE in the HTTP request
  parser, fixed in 1.30.1.
- CVE-2026-9256 — buffer overflow in `ngx_http_rewrite_module`
  (medium), fixed in 1.30.2.

#### Action required

No values-file changes. The ACR mirror must mirror the new
`nginxinc/nginx-unprivileged:1.30.2` tag and digest before rollout.

### Open Inwoner 2.1.2-rc1 → 2.1.2 (stable promotion)

Version of OIP goes from `2.1.2-rc1` to the stable `2.1.2` upstream
release.

#### Action required

No action required. The ACR mirror must mirror the new
`maykinmedia/open-inwoner:2.1.2` tag and digest.

### KISS: added Kennisbank role

Added the Kennisbank role to the KISS-client.

#### Action required

No action required.

### Zaakbrug: new sub-chart

The Zaakbrug Frank!Framework console is added as a new sub-chart
(`wearefrank/zaakbrug` 2.3.26, application image `1.26.13`). It runs in
the `podiumd` namespace as Deployment `podiumd-zaakbrug`, Service
`podiumd-zaakbrug:80` → container port `8080`. Default JVM heap is
`Xms=Xmx=4G` (`zaakbrug.frank.memory.{minimum,maximum}`); umbrella
values now set matching K8s resource requests/limits (`5Gi`/`6Gi`
memory, `250m`/`2` CPU). The sub-chart is disabled by default —
environments that need it set `zaakbrug.enabled: true`.

#### Action required

Three parties must each do work before Zaakbrug will come up cleanly:

**1. SSC — Postgres database**

Create the `zaakbrug` database on the shared Postgres flexible server
in the **normal fashion** (same procedure as for the other PodiumD
component databases — `openzaak`, `openklant`, `ita`, etc.):

- Database name: `zaakbrug`
- Owner role: `zaakbrug`
- Default privileges on the role for `public` schema
- `ssl: true` (TLS enforced by the server)
- **Provision at the minimum possible size** — Zaakbrug stores only
  Frank!Framework metadata + transient message-processing state and
  has no high-volume tables. Use the smallest tier/storage SKU
  permitted by the platform; scale up later from observed usage only
  if needed.

The chart sets `zaakbrug.connections.jdbc[0]` to point at the shared
Postgres host with database `zaakbrug` / user `zaakbrug`; the password
is supplied via the KeyVault secret listed below.

**2. SSC — KeyVault secrets (terraform)**

Add the following entries to the per-environment `keyvault.tfvars`
`passwords` array (the standard `random_password` +
`azurerm_key_vault_secret` loop generates a 32-char value once and
never overwrites it):

| KeyVault secret name | Used for | Pipeline env-var binding |
|---|---|---|
| `zaakbrug` | Postgres password for the `zaakbrug` DB user | `ZAAKBRUG_DATABASE_PASSWORD` |
| `zaakbrug-oauth-client-secret` | Keycloak `zaakbrug` client secret (Frank!Framework console SSO + KC realm-config seed) | `ZAAKBRUG_OAUTH_CLIENT_SECRET` |
| `zaakbrug-zaken-api-jwt-password` | JWT password for Zaakbrug's Zaken-API outbound credentials | `ZAAKBRUG_ZAKEN_API_JWT_PASSWORD` |

The values file (`applications/gemeenten/<gemeente>/<env>/podiumd.yml`)
already references these via `REP_ZAAKBRUG_DATABASE_PASSWORD_REP`,
`REP_ZAAKBRUG_OAUTH_CLIENT_SECRET_REP` and
`REP_ZAAKBRUG_ZAKEN_API_JWT_PASSWORD_REP` placeholders, which
`patch_values.py` substitutes at deploy time from the env-var bindings
above. No chart change is needed once the KV slots exist.

**3. Customer (gemeente) — DNS**

Create a CNAME record for the Zaakbrug hostname (default pattern
`<env>-zaakbrug.<gemeente-domain>`, e.g. `ontw-zaakbrug.dimpact.nl`)
pointing at the **Azure Application Gateway load balancer** that
terminates ingress traffic for the cluster (the same LB the other
PodiumD services already CNAME to). Without the DNS record, the
Gateway API HTTPRoute (`hr-zaakbrug-nginx` on `public-gateway`) has no
externally reachable hostname and OAuth2 callbacks from Keycloak will
fail.

The TLS certificate is issued automatically by cert-manager once the
CNAME resolves — no manual certificate handling required.

**4. Deploy pipeline (any consumer of this chart) — add the wearefrank helm repo**

Any pipeline that runs `helm dependency build` / `helm dependency
update` / `helm install|upgrade` against this umbrella chart **must
register the wearefrank helm repository** before the dependency step:

```bash
helm repo add wearefrank https://wearefrank.github.io/charts --force-update
helm repo update
```

The `Chart.yaml` `zaakbrug` dependency uses a direct URL today, so a
missing `helm repo add` does not fail the current build path — but the
omission is fragile (a future switch to a `@wearefrank` alias would
break the build silently, and `helm repo update` skips the repo
because it is not registered, so cached charts never refresh).

This applies to **every** consumer: the ExternalsPodiumD `Applications`
pipeline (`pipelines/application.yml`), any gemeente-specific deploy
pipeline, and the local `mini-helm-deploy.sh` used in the
`podiumd-infra` repo. The other subchart repositories already
registered there (`dimpact`, `bitnami`, `maykinmedia`, `wiremind`,
`kiss-elastic`, `zac`, `opentelemetry`, `zgw-office-addin`, `adfinis`,
`opstree`, `worth-nl`, …) should be joined by `wearefrank` for the
same consistency.