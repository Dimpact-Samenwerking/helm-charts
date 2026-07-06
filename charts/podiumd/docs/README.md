# charts/podiumd/docs

Documentation for the PodiumD Helm chart.

## Release documentation

| Document | Inhoud |
|---|---|
| [`releases/podiumd-4.8.md`](releases/podiumd-4.8.md) | Releaseoverzicht 4.8 — versietabellen per component, bestemd voor functioneel applicatiebeheer |

## Upgrade guides

See [`UPGRADING.md`](UPGRADING.md) for the official upgrade path and the index of all per-hop guides.

| Hop | Guide |
|---|---|
| 4.5.15 → 4.5.16 | [`upgrade-from-4.5.15-to-4.5.16.md`](upgrade-from-4.5.15-to-4.5.16.md) |
| 4.5.16 → 4.6.4  | [`upgrade-from-4.5.16-to-4.6.4.md`](upgrade-from-4.5.16-to-4.6.4.md) |
| 4.6.4 → 4.6.8   | [`upgrade-from-4.6.4-to-4.6.8.md`](upgrade-from-4.6.4-to-4.6.8.md) |
| 4.6.8 → 4.7.6   | [`upgrade-from-4.6.8-to-4.7.6.md`](upgrade-from-4.6.8-to-4.7.6.md) |
| 4.7.6 → 4.8.0   | [`upgrade-from-4.7.6-to-4.8.0.md`](upgrade-from-4.7.6-to-4.8.0.md) |

## Image manifests

| Directory | Inhoud |
|---|---|
| [`images/`](images/) | Per-release ACR-mirror manifests (`images-<version>.yaml`) en de cumulatieve [`images-baseline.yaml`](images/images-baseline.yaml) |
| [`images/acr-mirror-naming.md`](images/acr-mirror-naming.md) | ACR mirror naamgevingsconventie (strip-registry) |

## Topic-specific guides

| Document | Onderwerp |
|---|---|
| [`redis-ha.md`](redis-ha.md) | Redis HA cluster (OT redis-operator) |
| [`redis-ha-databases.md`](redis-ha-databases.md) | Database-allocatie per component |
| [`observability.md`](observability.md) | Observability (OTEL, Grafana, Loki) |
| [`resource-overview.md`](resource-overview.md) | CPU/memory resource requests |
| [`api-proxy-url-rewriting.md`](api-proxy-url-rewriting.md) | API-proxy URL-rewriting (BRP, BAG, KVK) |
| [`apisix-egress-gateway.md`](apisix-egress-gateway.md) | APISIX egress gateway |
| [`zac-brp-protocollering.md`](zac-brp-protocollering.md) | ZAC BRP protocollering (iConnect, eServices, 2Secure) |
| [`clamav-security-updates.md`](clamav-security-updates.md) | ClamAV virusscanner |
| [`keycloak-security-updates.md`](keycloak-security-updates.md) | Keycloak beveiliging |
| [`yaml-schema-validation.md`](yaml-schema-validation.md) | YAML-schema validatie in de chart |
| [`network-policy-analysis.md`](network-policy-analysis.md) | Netwerkbeleid analyse |
| [`security-review.md`](security-review.md) | Beveiligingsreview |
| [`enabling-pabc.md`](enabling-pabc.md) | PABC activeren |
| [`openzaak-db-connection-pooling.md`](openzaak-db-connection-pooling.md) | Open Zaak database connection pooling |
| [`openzaak-known-issues.md`](openzaak-known-issues.md) | Open Zaak bekende problemen |
| [`openarchiefbeheer-known-issues.md`](openarchiefbeheer-known-issues.md) | Archiefbeheer bekende problemen |
| [`openbeheer-known-issues.md`](openbeheer-known-issues.md) | Open Beheer bekende problemen |
| [`openinwoner-outgoing-request-logging.md`](openinwoner-outgoing-request-logging.md) | Open Inwoner uitgaande request logging |
| [`migrating-to-keycloak-operator.md`](migrating-to-keycloak-operator.md) | Migratie naar keycloak-operator |
| [`migrating-to-kiss-2.md`](migrating-to-kiss-2.md) | Migratie naar KISS 2 |
| [`agw-apisix-certmanager-tls-design.md`](agw-apisix-certmanager-tls-design.md) | API gateway TLS-ontwerp met cert-manager |
