# Upgrade guide: PodiumD 4.7.1 → 4.7.2

## Changes

### Patch version for OIP

Version of OIP goes from 2.1.2-rc to 2.1.2

#### Action required

No action required.

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