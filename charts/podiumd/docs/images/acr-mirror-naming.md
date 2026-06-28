# ACR mirror naming reference

The podiumd chart targets `acrprodmgmt.azurecr.io` (set via
`global.imageRegistry` in each gemeente's `ExternalsPodiumD/.../podiumd.yml`).
Images are mirrored from public registries into ACR by the SSC-Hosting
import pipeline, which reads the per-release `charts/podiumd/docs/images/images-*.yaml`
manifests.

**The `name:` field in those manifests is the ACR mirror repo name, not the
upstream image name.** The upstream image lives at `url:`. There is no single
rule that derives one from the other — drop-namespace, drop-hyphen, and
Dutch-rename all occur. Always look up the existing mirror name in this table
before adding a new entry.

## Authoritative source

This table is reconstructed from:

- `charts/podiumd/docs/images/images-4.7.0.yaml` (the most complete published
  manifest).
- Per-gemeente repository overrides in
  `ExternalsPodiumD/applications/gemeenten/<gem>/<env>/podiumd.yml`.
- Live `pod.spec.containers[*].image` on `aks-blue-ontw-dim1/podiumd` —
  ground truth for what ACR actually serves.

The convention is enforced at import time: if a manifest entry uses the wrong
`name:`, the import will create a mismatching ACR repo (or worse, succeed
into the wrong repo) and pods will `ImagePullBackOff` or — silently — pull
an out-of-date image from a stale mirror under the upstream-shaped name.

## Mapping

Sorted by ACR mirror name. `name:` in `images-*.yaml` MUST match column 2.
Column 1 lists the canonical upstream `url:` value (without tag).

| upstream `url:` (canonical)                                  | ACR `name:` (mirror repo)               | notes                                       |
|--------------------------------------------------------------|------------------------------------------|---------------------------------------------|
| `docker.io/apache/apisix`                                    | `apisix`                                 |                                             |
| `docker.io/library/busybox`                                  | `busybox`                                |                                             |
| `docker.io/clamav/clamav`                                    | `clamav`                                 |                                             |
| `docker.io/clamav/clamav-prometheus-exporter` *              | `clamav_exporter`                        | underscore, not hyphen                      |
| `ghcr.io/info-nl/contact-adapter` *                          | `contact-adapter`                        |                                             |
| `ghcr.io/info-nl/contact-frontend` *                         | `contact-frontend`                       |                                             |
| `ghcr.io/info-nl/contact-sync` *                             | `contact-sync`                           |                                             |
| `docker.io/curlimages/curl`                                  | `curl`                                   |                                             |
| `docker.io/elastic/eck-operator`                             | `eck-operator`                           |                                             |
| `docker.io/elastic/elasticsearch`                            | `elasticsearch/elasticsearch`            | keeps `<vendor>/<repo>` path                |
| `docker.io/elastic/enterprise-search`                        | `enterprise-search/enterprise-search`    | keeps `<vendor>/<repo>` path                |
| `gcr.io/etcd-development/etcd`                               | `etcd`                                   |                                             |
| `docker.io/gotenberg/gotenberg`                              | `gotenberg`                              |                                             |
| `docker.io/redhat/ubi8-micro`                                | `infinispan-init` *                      | infinispan init container                   |
| `docker.io/infinispan/server`                                | `infinispan-server`                      |                                             |
| `ghcr.io/interne-taak-afhandeling/internetaakafhandeling.poller` | `internetaakafhandeling.poller`      | dot in repo name                            |
| `ghcr.io/interne-taak-afhandeling/internetaakafhandeling.web`    | `internetaakafhandeling.web`         | dot in repo name                            |
| `docker.io/alpine/k8s`                                       | `k8s`                                    | drops `alpine/` namespace                   |
| `docker.io/lachlanevenson/k8s-kubectl`                       | `k8s-kubectl`                            |                                             |
| `docker.io/groundnuty/k8s-wait-for`                          | `k8s-wait-for`                           |                                             |
| `quay.io/keycloak/keycloak`                                  | `keycloak`                               |                                             |
| `quay.io/keycloak/keycloak-config-cli` *                     | `keycloak-config-cli`                    |                                             |
| `quay.io/keycloak/keycloak-operator`                         | `keycloak-operator`                      |                                             |
| `docker.io/elastic/kibana`                                   | `kibana/kibana`                          | keeps `<vendor>/<repo>` path                |
| `docker.io/nginxinc/nginx-unprivileged`                      | `nginx-unprivileged`                     | keeps hyphen (unlike open-*)                |
| `docker.io/library/nginx` (or bitnami)                       | `nginx`                                  | sub-chart sidecar default override          |
| `docker.io/maykinmedia/objecten-api`                         | `objecten`                               | drops `-api`                                |
| `docker.io/maykinmedia/objecttypes-api`                      | `objecttypen`                            | Dutch rename + drop `-api`                  |
| `quay.io/oauth2-proxy/oauth2-proxy`                          | `oauth2-proxy`                           |                                             |
| `docker.io/openpolicyagent/opa`                              | `opa`                                    |                                             |
| `docker.io/worthnl/notifynl-omc`                             | `omc`                                    | renamed                                     |
| `ghcr.io/openbeheer/open-beheer` (best-guess upstream)       | `open-beheer`                            | KEEPS hyphen (exception to open-* pattern)  |
| `docker.io/maykinmedia/open-archiefbeheer`                   | `openarchiefbeheer`                      | drops hyphen                                |
| `docker.io/openformulieren/open-forms`                       | `openformulieren`                        | Dutch rename + drop hyphen                  |
| `docker.io/maykinmedia/open-inwoner`                         | `openinwoner`                            | drops hyphen ← common mistake               |
| `docker.io/maykinmedia/open-klant`                           | `openklant`                              | drops hyphen                                |
| `docker.io/maykinmedia/open-notificaties`                    | `opennotificaties`                       | drops hyphen                                |
| `docker.io/openzaak/open-zaak`                               | `openzaak`                               | drops hyphen                                |
| `ghcr.io/open-telemetry/opentelemetry-collector-contrib`     | `opentelemetry-collector-contrib`        |                                             |
| `ghcr.io/info-nl/pabc-api` *                                 | `pabc-api`                               |                                             |
| `docker.io/brpapi/personen-mock` *                           | `personen-mock`                          | brp-personen-mock sub-chart                 |
| `docker.io/bitnami/rabbitmq` (or library)                    | `rabbitmq`                               |                                             |
| `docker.io/library/redis` (or bitnami)                       | `redis`                                  |                                             |
| `docker.io/oliver006/redis_exporter`                         | `redis-exporter`                         | hyphen, not underscore (unlike clamav)      |
| `docker.io/spotahome/redis-operator`                         | `redis-operator`                         |                                             |
| `docker.io/maykinmedia/referentielijsten-api`                | `referentielijsten-api`                  | keeps `-api` (unlike objecten)              |
| `docker.io/library/solr`                                     | `solr`                                   |                                             |
| `docker.io/apache/solr-operator`                             | `solr-operator`                          |                                             |
| `ghcr.io/infonl/zaakafhandelcomponent`                       | `zac`                                    | renamed                                     |
| `ghcr.io/infonl/zgw-office-addin-backend`                   | `zgw-office-addin-backend`              |                                             |
| `ghcr.io/infonl/zgw-office-addin-frontend`                  | `zgw-office-addin-frontend`             |                                             |
| `docker.io/pravega/zookeeper`                                | `zookeeper`                              |                                             |
| `docker.io/pravega/zookeeper-operator`                       | `zookeeper-operator`                     |                                             |

`*` = upstream URL is a best-guess based on the live ACR repo name; verify
against the actual upstream registry before relying on it for a new mirror.

## Pattern guidelines (not rules — verify against the table)

Recurring mappings observed in this list:

1. **Maykin "open-X" products lose the hyphen**: `open-inwoner`→`openinwoner`,
   `open-klant`→`openklant`, `open-notificaties`→`opennotificaties`,
   `open-archiefbeheer`→`openarchiefbeheer`, `open-zaak`→`openzaak`.
   Exception: `open-beheer` keeps its hyphen.
2. **`-api` suffix dropped only sometimes**: `objecten-api`→`objecten`,
   `objecttypes-api`→`objecttypen`. But `referentielijsten-api` keeps the
   suffix and `pabc-api` keeps it too.
3. **Dutch rename**: `objecttypes-api`→`objecttypen`, `open-forms`→`openformulieren`.
   Anything Maykin-shaped that has an English root and a Dutch counterpart
   tends to ship under the Dutch name in ACR.
4. **Most other images keep their hyphens**: `nginx-unprivileged`,
   `keycloak-operator`, `solr-operator`, `redis-operator`, `redis-exporter`,
   `eck-operator`, `oauth2-proxy`, `pabc-api`, `personen-mock`,
   `zgw-office-addin-*`.
5. **A few keep their vendor path** (`elasticsearch/elasticsearch`,
   `kibana/kibana`, `enterprise-search/enterprise-search`) — these are the
   Elastic-stack images, which the ECK operator addresses by the
   `<product>/<product>` shape.
6. **Some are renamed**: `zaakafhandelcomponent`→`zac`,
   `notifynl-omc`→`omc`, `clamav-prometheus-exporter`→`clamav_exporter`.

## Workflow for a new image in a release manifest

1. Find the upstream registry/repo (the `url:` value).
2. Look up the ACR mirror name in this table by `url:`. If it's not in the
   table:
   - Check the running pods on a deployed cluster
     (`kubectl --context aks-blue-ontw-dim1 -n podiumd get pods -o jsonpath='{range .items[*].spec.containers[*]}{.image}{"\n"}{end}' | sort -u`)
     to see whether the image is already mirrored.
   - If it is already mirrored, use that ACR repo name and update this
     table.
   - If it is a brand-new mirror, follow the naming guideline closest to
     the upstream shape (usually: drop everything before the last `/`, then
     apply the Maykin "drop the hyphen" rule for `open-*` images), but
     **coordinate with SSC-Hosting** before adding the entry — they decide
     the actual ACR repo name when they create it.
3. Write the entry as:
   ```yaml
   - name: <acr-mirror-name>
     url: <upstream-canonical-url-no-tag>
     version: "<tag>"
     digest: "sha256:<digest>"
   ```
4. After publishing the manifest, verify on a deployed cluster that the
   image pulls cleanly. A `name:` that mismatches the ACR repo will
   manifest as `ImagePullBackOff` on the first rollout that touches that
   image.

## Common mistakes to avoid

- Writing `name: open-inwoner` (upstream shape) when the ACR mirror is
  `openinwoner`. The upstream URL stays hyphenated; only the mirror name
  loses the hyphen.
- Copying `name:` and `url:` from a freshly fetched docker.io manifest
  without checking this table — the fetcher reports the upstream-shaped
  repo, not the ACR-shaped one.
- Assuming `name == basename(url)`: it's true most of the time, but the
  Maykin open-* family and the Elastic stack are exceptions.
