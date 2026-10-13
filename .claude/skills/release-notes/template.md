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
| {component} | {oud} → {nieuw} (chart {oud} → {nieuw}) | **{Klein|Middel|Groot}**: {reden} | {wat wij in de chart hebben aangepast} | {wat SSC moet doen, of: Nieuwe image spiegelen} |

{Nieuwe digests voor dezelfde tags, als die er zijn.}

## Configuratiewijzigingen

| Wijziging | Impact helm-charts | Impact SSC |
| --- | --- | --- |
| {wijziging} ([{Jira}](https://dimpact.atlassian.net/browse/{Jira})) | {wat er in de chart verandert} | {actie, of: Geen} |

## Wat wij hebben gecontroleerd

- **{Live of deploytest}:** {omgeving, wat gecontroleerd, resultaat}.
- **Chartcontroles:** {welke `verify-podiumd`-checks}.
- **Niet getest:** {wat alleen met chartcontroles is gevalideerd, of uitgesteld}.
- **Bekende problemen buiten deze release:** {indien van toepassing}.

## Documentatie voor SSC

- [Upgradehandleiding {baseline} → {version}](https://github.com/Dimpact-Samenwerking/helm-charts/blob/main/charts/podiumd/docs/_UPGRADE_PATHS/{baseline}-to-{version}-upgrade.md)
- [Values-wijzigingen](https://github.com/Dimpact-Samenwerking/helm-charts/blob/main/charts/podiumd/docs/_UPGRADE_PATHS/{baseline}-to-{version}-values-deltas.md)
- [Gemeentespecifieke punten](https://github.com/Dimpact-Samenwerking/helm-charts/blob/main/charts/podiumd/docs/_UPGRADE_PATHS/{baseline}-to-{version}-gemeente-specific.md)
- [Images (`images-{version}.yaml`)](https://github.com/Dimpact-Samenwerking/helm-charts/blob/main/charts/podiumd/docs/images/images-{version}.yaml)
