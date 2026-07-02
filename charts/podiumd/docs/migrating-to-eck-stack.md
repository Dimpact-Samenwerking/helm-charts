# Migratie: legacy kiss-elastic naar eck-operator + eck-stack

Dit runbook beschrijft de overstap van de legacy `kiss-elastic` subchart naar
Elastic's officiele Helm-charts (`eck-operator` + `eck-stack`), zoals ingevoerd
door PR #331. Uitgangspunt: **migreren zonder verlies van data**.

Getest op een ontwikkelomgeving met data (test00), zie het onderdeel
[Validatie](#5-validatie).

## 1. Wat verandert er op chart-niveau

| | Voor | Na |
|---|---|---|
| KISS Elasticsearch | `kiss-elastic` subchart (1.1.0), die zelf de eck-operator meebracht | `eck-stack` dependency (0.19.0, alias `kiss-eck`) |
| ECK operator | Uit de `kiss-elastic` subchart, of los geinstalleerd per omgeving | **Centraal** in de umbrella: root-level `eck-operator` (3.4.0) met `managedNamespaces: [podiumd]` |
| OIP Elasticsearch | `eck-elasticsearch` uit de `openinwoner` subchart | Ongewijzigd; blijft uit de `openinwoner` subchart komen |
| OIP operator | `openinwoner.eck-operator.enabled: false` | Ongewijzigd; OIP gebruikt de centrale operator |

Kernprincipe: de ECK-operator wordt centraal geimplementeerd in PodiumD, niet
meer vanuit een subchart van KISS of OIP. KISS en OIP leveren alleen nog hun
eigen Elasticsearch-resource; de centrale operator reconcilet ze beide in de
`podiumd` namespace.

## 2. Resource-naming: geen wijziging, dus data blijft behouden

De ECK-operator leidt de StatefulSet- en PVC-namen af van de naam van de
`Elasticsearch`-resource en van de nodeSet-naam. Zolang die gelijk blijven,
wordt de bestaande StatefulSet in stand gehouden en blijven de PVC's (de data)
staan.

| Resource | Naam voor | Naam na |
|---|---|---|
| `Elasticsearch` (KISS) | `kiss` | `kiss` (via `fullnameOverride: kiss`) |
| `Kibana` / `EnterpriseSearch` (KISS) | `kiss` | `kiss` |
| nodeSet | `default` | `default` |
| StatefulSet | `kiss-es-default` | `kiss-es-default` |
| PVC's | `elasticsearch-data-kiss-es-default-{0,1,2}` | idem |
| `Elasticsearch` (OIP) | `openinwoner-elasticsearch` | `openinwoner-elasticsearch` |

**Belangrijk:** wijzig de nodeSet-naam niet (houd `default`). Een andere
nodeSet-naam laat de operator een nieuwe StatefulSet aanmaken en data
herbalanceren, wat wel disruptief is.

De `Elasticsearch`-spec is voor en na functioneel identiek (zelfde `version`,
`nodeSets[].name`, `count` en `config`). De enige echte wijziging op de CR is
het Helm-label `helm.sh/chart` (`kisselastic-1.1.0` wordt
`eck-elasticsearch-0.19.x`). De ECK-operator herbouwt de StatefulSet daardoor
niet en herstart de pods niet.

## 3. Impact op gemeentelijke helm-values

### KISS
- Verwijder het `kisselastic:` blok. Vervang door `kiss-eck:` (eck-stack) en
  een root-level `eck-operator:` blok. Zie `values.yaml` voor de defaults.
- nodeSets, resources en crawler-instellingen zijn nu omgevingsspecifiek in te
  vullen onder `kiss-eck.eck-enterprise-search.config` en
  `kiss-eck.eck-elasticsearch.nodeSets` (dit lost DS-5060 op: crawler-config
  per omgeving).
- De tag `contact` blijft KISS aansturen (`kiss-eck` heeft `tags: [kiss-eck, contact]`).

### OIP (openinwoner)
- Geen nieuwe dependency nodig. OIP levert `eck-elasticsearch` al via de
  `openinwoner` subchart.
- Zorg dat `openinwoner.eck-operator.enabled: false` blijft staan, zodat OIP de
  centrale operator gebruikt en niet zijn eigen `openinwoner-elastic-operator`
  opzet.
- nodeSets voor OIP staan onder `openinwoner.eck-elasticsearch.nodeSets`
  (omgevingsspecifiek).

### Centrale operator
- `eck-operator.enabled: true` en `eck-operator.managedNamespaces: [podiumd]`
  (of de namespace waarin PodiumD draait). De operator moet de namespace van
  zowel `kiss` als `openinwoner-elasticsearch` dekken.

## 4. Migratie-stappen voor SSC (omgeving die al draait)

De KISS Elasticsearch-migratie zelf is een metadata-only wijziging (zie sectie
2). Het aandachtspunt zit in de **operator-overname** wanneer een omgeving nu
een losse `elastic-operator` Helm-release draait (bijvoorbeeld geinstalleerd via
`scripts/deploy-operators.sh`).

### 4a. Als de omgeving een losse elastic-operator draait

De centrale umbrella-operator wil dezelfde resources beheren als de losse
release. Strip daarom eerst de Helm-ownership van de bestaande
operator-resources, zodat de umbrella ze kan adopteren:

```bash
# Zie scripts/archive/strip-eck-helm-annotations.sh (podiumd-infra) voor het
# volledige script. Het verwijdert meta.helm.sh/release-* annotaties en de
# managed-by label van: serviceaccount/elastic-operator,
# service/elastic-operator-webhook, statefulset/elastic-operator, en de
# bijbehorende clusterroles/-binding.
```

Alternatief (eenvoudiger, aanbevolen voor de eerste uitrol): laat de losse
operator staan en zet in de omgevings-values `eck-operator.enabled: false`. De
umbrella swapt dan alleen de KISS Elasticsearch-chart (kisselastic -> kiss-eck)
en de bestaande operator blijft reconcilen. De operator-centralisatie kan als
aparte, latere stap.

> Let op de operator-versiesprong. Bij het overnemen door de umbrella-operator
> (3.4.0) kan de `elastic-operator` StatefulSet een immutable
> `spec.selector`-conflict geven bij `helm upgrade`. Dat is op te lossen door de
> `elastic-operator` StatefulSet te verwijderen (bevat geen data) en helm de
> nieuwe te laten aanmaken.

### 4b. De upgrade

1. Maak een backup/snapshot van de Elasticsearch-data (of noteer minimaal de
   index/doc-counts, zie sectie 5).
2. Voer `helm upgrade` uit met de nieuwe chart en de aangepaste
   omgevings-values.
3. De `kiss` en `openinwoner-elasticsearch` StatefulSets worden in-place
   bijgewerkt (niet herbouwd).

## 5. Validatie

Vastleggen voor en na de upgrade:

```bash
NS=podiumd
# StatefulSet UID (moet identiek blijven = niet herbouwd)
kubectl get sts kiss-es-default -n $NS -o jsonpath='{.metadata.uid}{"\n"}'
# PVC's (moeten blijven bestaan)
kubectl get pvc -n $NS -l 'elasticsearch.k8s.elastic.co/cluster-name=kiss'
# Doc-counts als data-ijkpunt
PW=$(kubectl get secret kiss-es-elastic-user -n $NS -o go-template='{{.data.elastic|base64decode}}')
kubectl exec -n $NS kiss-es-default-0 -c elasticsearch -- \
  curl -s -k -u "elastic:$PW" "https://localhost:9200/_cat/indices/search-*?v&h=index,docs.count"
```

Na de upgrade moeten StatefulSet-UID, PVC's en doc-counts ongewijzigd zijn en
moet de `Elasticsearch`-health `green` zijn.

### Resultaat op test00 (02-07-2026)
Met een realistische data-baseline (475 documenten: `search-kennisbank` +
`search-vac`) is de chart-swap getest: StatefulSet `kiss-es-default` behield
zijn UID (niet herbouwd), de PVC's bleven staan, de ES bleef `green` en alle
475 documenten waren intact. De migratie is een metadata-only wijziging op de
Elasticsearch-CR, zonder dataverlies of verstoring.

## 6. Rollback

Omdat de migratie een chart-swap is en de onderliggende Elasticsearch-data
(PVC's) niet worden aangeraakt, is terugrollen naar de `kiss-elastic` chart
mogelijk zonder dataverlies: `helm rollback` of opnieuw `helm upgrade` met de
oude chart. De StatefulSet en PVC-namen blijven in beide richtingen gelijk.
