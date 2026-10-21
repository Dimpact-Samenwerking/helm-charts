# PodiumD {version}

{Patch|Minor}release op {baseline}, uitgebracht op {datum} ([#{release PR}](https://github.com/Dimpact-Samenwerking/helm-charts/pull/{release PR})).

Wat gemeenten zelf moeten doen staat op de [releasepagina in de wiki](https://dimpact.atlassian.net/wiki/spaces/PCP/pages/7602191/Releases+PodiumD).

## In het kort

- {aantal} componenten bijgewerkt; grootste stap: {component en waarom}.
- {aanleiding van de release, als die er is, bijvoorbeeld een beveiligingsupdate}.
- Impact voor SSC: {klein|middel|groot}, {één zin waarom}.
- {waar en hoe getest}.

## Bijgewerkte componenten

| Component | Versie | Omvang | Impact helm-charts | Impact SSC |
| --- | --- | --- | --- | --- |
| {component} | {oud} → {nieuw} (chart {oud} → {nieuw}) | **{Klein|Middel|Groot}**: {reden} | {wat wij in de chart hebben aangepast} | {wat SSC moet doen, of: Nieuwe image mirroren} |

{Nieuwe digests voor dezelfde tags, als die er zijn.}

## Configuratiewijzigingen

| Wijziging | Impact helm-charts | Impact SSC |
| --- | --- | --- |
| {wijziging} ([{Jira}](https://dimpact.atlassian.net/browse/{Jira})) | {wat er in de chart verandert} | {actie, of: Geen} |

## Wat wij hebben gecontroleerd

- **{Live of deploytest}:** {omgeving, wat gecontroleerd, resultaat}.
- **Chartcontroles:** {welke `verify-podiumd`-checks}.
- **Niet getest:** {wat alleen met chartcontroles is gevalideerd, of uitgesteld}.
- **Bekende problemen buiten deze release:** {indien van toepassing}, zie
  [Bekende problemen](#bekende-problemen).

## Bekende problemen

<!-- Alleen als er bekende fouten in de applicaties zijn. Bron: de tabel in README.md van
     infonl/podiumd-known-issues (privé), zie "Bekende problemen" in SKILL.md. Noem alleen wat
     gemeenten of SSC merken; geen reproductiestappen. Beveiligingsbevindingen alleen als aantal
     per ernst in de tabel hieronder. -->

| Ernst | Probleem | Component | Gevolg | Oplossing |
| --- | --- | --- | --- | --- |
| {Kritiek, Hoog, Middel of Opgelost} | {wat er misgaat} | {component en versie} | {wat gemeenten of SSC merken} | {upstream-versie met de fix, onze PR of Jira-issue, workaround, of "Nog geen"} |

### Beveiligingsbevindingen

Bevindingen met gevolgen voor de beveiliging noemen we alleen als aantal per
ernst, net als de CVE's: de details maken we pas bekend nadat ze bij de
leveranciers zijn gemeld of opgelost.

| Ernst | Aantal | Met oplossing of workaround |
| --- | --- | --- |
| Kritiek | {n} | {n: PR of Jira-issue, of "-"} |
| Hoog | {n} | {…} |
| Middel | {n} | {…} |
| Laag | {n} | {…} |

## Nog open voor {version}

<!-- Alleen zolang de release niet uit is. -->

Bron: [{Jira} "PodiumD {version} bouwen"](https://dimpact.atlassian.net/browse/{Jira})
(stand {datum}). Van de {n} subtaken zijn er {n} klaar, {n} in review,
{n} in uitvoering en {n} nog niet gestart. De PR-status komt uit GitHub.

### In review

| Jira | Onderwerp | PR |
| --- | --- | --- |
| [{Jira}](https://dimpact.atlassian.net/browse/{Jira}) | {onderwerp} | [#{PR}](https://github.com/Dimpact-Samenwerking/helm-charts/pull/{PR}) |

### In uitvoering

{zelfde tabel}

### Nog niet gestart

{zelfde tabel}

## Review en kwaliteit

Bron: GitHub, PR's naar `feature/podiumd-{version}` (stand {datum}).

- **{n} PR's**, waarvan {n} gemerged en {n} open; samen +{n} / −{n} regels.
- **{n} reviews**: {n} goedkeuringen en {n} keer "changes requested".
- **Reviewers:** {n} collega's naast de auteur.
- **Reviewdiscussies:** {n}, waarvan {n} opgelost. Nog open: {PR's}.
- **Doorlooptijd:** mediaan {n} dag van openen tot merge.
- **Zonder review gemerged:** {grote PR's met wat het testte; kleine alleen tellen}.
- **Release-PR:** {commits, bestanden, regels, reviews}.

## Documentatie voor SSC

- [Upgradehandleiding {baseline} → {version}](https://github.com/Dimpact-Samenwerking/helm-charts/blob/main/charts/podiumd/docs/_UPGRADE_PATHS/{baseline}-to-{version}-upgrade.md)
- [Values-wijzigingen](https://github.com/Dimpact-Samenwerking/helm-charts/blob/main/charts/podiumd/docs/_UPGRADE_PATHS/{baseline}-to-{version}-values-deltas.md)
- [Gemeentespecifieke punten](https://github.com/Dimpact-Samenwerking/helm-charts/blob/main/charts/podiumd/docs/_UPGRADE_PATHS/{baseline}-to-{version}-gemeente-specific.md)
- [Images (`images-{version}.yaml`)](https://github.com/Dimpact-Samenwerking/helm-charts/blob/main/charts/podiumd/docs/images/images-{version}.yaml)
