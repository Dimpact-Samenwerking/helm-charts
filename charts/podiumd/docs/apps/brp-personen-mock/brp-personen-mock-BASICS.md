# BRP Personen Mock — Basics

## Management summary

BRP Personen Mock is a stand-in for the Dutch personal-records registry (BRP,
"Basisregistratie Personen"). In development and test environments it answers
the same API questions a real BRP connection would — "who lives at this
address", "what are this citizen's details" — but with fake test persons, so no
real citizen data is ever involved. PodiumD applications such as Open Inwoner,
KISS and ZAC need those answers to work; the mock lets a test environment run
without an expensive, access-controlled connection to the real registry. It
needs nothing to run: no database, no storage, no login — a single small
container. It is for test environments only and must never be used in
production.

## What it is

- Upstream: the official mock of the **Haal Centraal BRP Personen Bevragen
  API**, published by the BRP API programme
  ([github.com/BRP-API](https://github.com/BRP-API)).
- Image: `ghcr.io/brp-api/personen-mock:2.7.0-202606230850` (an ASP.NET Core
  service; the ConfigMap sets `ASPNETCORE_ENVIRONMENT=Release` and
  `ASPNETCORE_URLS=http://+:5010`).
- **Not part of the podiumd umbrella chart.** It is its own chart in this repo,
  `charts/brp-personen-mock/` (chart version 1.2.9, appVersion 2.7.0), deployed
  as a **separate Helm release alongside podiumd** — usually into the same
  `podiumd` namespace so consumers can reach it by short service name.
- Runtime components: a single Deployment `brp-personen-mock` (1 replica,
  hard-coded in the template), a ClusterIP Service `brp-personen-mock` on port
  5010, a ConfigMap and a ServiceAccount. No probes, no PDB, no ingress
  template.
- Test data is baked into the image — the mock answers Haal Centraal BRP
  queries (e.g. `POST /haalcentraal/api/brp/personen`) from a fixed set of
  fictitious persons.

## Required resources

### Database

None. All test-person data is bundled in the image; nothing is persisted.

### Storage

None. No PVC is rendered.

### Routing / exposure (NGINX Gateway Fabric)

Cluster-internal only. No HTTPRoute exists on the Dimpact clusters and none
should be created — the mock has no authentication and must not be reachable
from outside the cluster. Consumers use the ClusterIP service:
`http://brp-personen-mock.<namespace>.svc.cluster.local:5010`
(or `http://brp-personen-mock:5010` from within the same namespace).

### Other dependencies

None of its own (no Redis, no Keycloak client, no notificaties registration).
It exists purely to be a dependency *of* other apps:

- **Open Inwoner** — Haal Centraal BRP service configuration
  (`openinwoner.settings.brpVersion` in the podiumd values; the service URL is
  configured in the app).
- **KISS** — `kiss.settings.haalCentraal.baseUrl` / `apiKey`.
- **ZAC** — `zac.brpApi.url` / `zac.brpApi.apiKey`.
- **api-proxy** — in environments that route BRP traffic through the proxy,
  the `apiproxy` BRP location (`path: /haalcentraal/api/brp/`) can target the
  mock instead of an external vendor.

## CPU and memory

Chart defaults (`charts/brp-personen-mock/values.yaml`; matches
`docs/misc/resource-overview.md`, which marks this component *"Test environments
only"*):

| Container | CPU request | Mem request | CPU limit | Mem limit |
|-----------|-------------|-------------|-----------|-----------|
| brp-personen-mock | 10m | 150Mi | not set (burstable) | not set (burstable) |

Observed usage (2026-07-10): `1m / 83Mi` on aks-blue-ontw-dimp and
`1m / 146Mi` on aks-blue-accp-dimp. The defaults are adequate as-is; no
production sizing applies because the mock is never deployed to production.

## Integrating BRP Personen Mock as a new app

1. **Decide the namespace.** Install into the same namespace as the podiumd
   release (normally `podiumd`) so consuming apps can use the short service
   name `brp-personen-mock`.
2. **Install as a separate Helm release** (it is not enabled via the podiumd
   umbrella values):

   ```bash
   helm upgrade --install brp-personen-mock charts/brp-personen-mock/ \
     --namespace podiumd
   ```

   The defaults need no overrides; pin a different image via `image.tag` only
   if a newer mock build is required.
3. **Point the consuming apps at the mock** in the environment's podiumd
   values, e.g.:
   - KISS: `kiss.settings.haalCentraal.baseUrl: http://brp-personen-mock:5010/haalcentraal/api/brp/` (any non-empty `apiKey` — the mock does not check it).
   - ZAC: `zac.brpApi.url: http://brp-personen-mock:5010/haalcentraal/api/brp` (dummy `apiKey.value`).
   - Open Inwoner: configure the Haal Centraal BRP service URL to the mock
     service and set `openinwoner.settings.brpVersion` as required.
4. **No DNS, HTTPRoute, Keycloak client or Open Zaak registration** is needed —
   the mock is cluster-internal and unauthenticated.
5. **Verify**: pod `brp-personen-mock` Running in the namespace, and a test
   query returns a fictitious person:

   ```bash
   kubectl -n podiumd run brp-mock-test --rm -it --restart=Never \
     --image=curlimages/curl -- \
     curl -s -X POST http://brp-personen-mock:5010/haalcentraal/api/brp/personen \
       -H 'Content-Type: application/json' \
       -d '{"type":"RaadpleegMetBurgerservicenummer","burgerservicenummer":["999993653"],"fields":["burgerservicenummer","naam"]}'
   ```

6. **Never deploy to production.** Production environments must connect the
   consuming apps to a real BRP/Haal Centraal provider (directly or via
   api-proxy) instead.

## Related documents

None — this folder has only the BASICS file; no deep-dive documents exist yet
for this component.
