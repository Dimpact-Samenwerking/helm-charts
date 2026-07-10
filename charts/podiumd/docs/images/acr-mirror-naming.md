# ACR mirror naming reference

The podiumd chart targets `acrprodmgmt.azurecr.io` (set via
`global.imageRegistry` in each gemeente's `ExternalsPodiumD/.../podiumd.yml`).
Images are mirrored from public registries into ACR by the SSC-Hosting
import pipeline, which reads the per-release `charts/podiumd/docs/images/images-*.yaml`
manifests.

## Convention (current): strip the registry, keep the full upstream path

The ACR mirror repo name is the **upstream image reference with only the
registry host stripped** — the full `<namespace>/<repo>` path is kept verbatim.
No drop-namespace, no drop-hyphen, no Dutch-rename. The rule is mechanical:

```
quay.io/keycloak/keycloak            -> keycloak/keycloak
docker.io/maykinmedia/open-inwoner   -> maykinmedia/open-inwoner
ghcr.io/infonl/zaakafhandelcomponent -> infonl/zaakafhandelcomponent
docker.io/library/redis              -> library/redis
```

So the mirrored image is `<global.imageRegistry>/<namespace>/<repo>:<tag>`,
e.g. `acrprodmgmt.azurecr.io/maykinmedia/open-inwoner:2.3.0`.

For any **new** image there is nothing to look up — just strip the registry
host from the upstream `url:`. The `name:` in an `images-*.yaml` manifest is
`strip_registry(url)`.

### Tooling

- **Script:** [`charts/podiumd/scripts/mirror-strip-registry.py`](../../scripts/mirror-strip-registry.py)
  - `--gen-manifest` prints `name:`/`url:` for every image under this convention.
  - `mirror-strip-registry.py <gemeente>/podiumd.yml` migrates a values file
    from the legacy names below to the new ones (`--dry-run` diff by default,
    `--in-place` to write). Handles the inline, split (`registry:`+`repository:`)
    and `imageName:` shapes.
- **Complete manifest:** [`images-baseline.yaml`](images-baseline.yaml)
  (every image, `name = strip_registry(url)`). `--gen-manifest` regenerates the
  per-release-delta subset; the long-stable gap-fillers in that file are
  hand-maintained.

> **Migration:** run the script against each `ExternalsPodiumD/.../podiumd.yml`
> and re-import the affected ACR repos under the new names. The legacy table
> below is **frozen** — kept only as the old-name → upstream reference the
> migration relies on. It is **not** maintained for new images; do not add rows.

---

## Legacy translation table (deprecated — migration reference only)

> ⚠️ Superseded by the strip-registry convention above. These were the old,
> hand-translated ACR names (drop-namespace / drop-hyphen / Dutch-rename). Use
> only to map an existing environment off the old scheme.

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
