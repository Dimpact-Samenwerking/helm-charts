---
marp: true
paginate: true
title: PodiumD {version}
---

# PodiumD {version}

{Patch|Minor}release op {baseline}, {datum}

Integratie, impact en validatie

---

## In het kort

- {aantal} componenten bijgewerkt; grootste stap: **{component}**
- {aanleiding}
- Impact voor SSC: **{klein|middel|groot}**
- {waar getest}

---

## Bijgewerkte componenten

| Component | Versie | Omvang |
| --- | --- | --- |
| {component} | {oud} → {nieuw} | {Klein|Middel|Groot} |

---

## Impact

**helm-charts**
- {wijziging in de chart}

**SSC**
- {actie}

---

## Wat wij hebben gecontroleerd

- {omgeving: wat en resultaat}
- {chartcontroles}
- {wat niet getest is}

---

## Nog open voor {version} ({Jira})

<!-- Alleen zolang de release niet uit is; splits over twee slides als het niet past. -->

{n} subtaken: **{n} klaar**, {n} in review, {n} in uitvoering, {n} nog niet gestart

**In review**
- {onderwerp (#PR)}

**In uitvoering**
- {onderwerp (#PR)}

---

## Review en kwaliteit

- **{n} PR's** naar de releasebranch: {n} gemerged, {n} open
- **{n} reviews**, {n} goedkeuringen; {n} reviewers naast de auteur
- **{n} reviewdiscussies, {n} opgelost**
- Doorlooptijd: mediaan **{n} dag**
- {zonder review gemerged, met wat het testte}

---

## Meer informatie

- Acties voor gemeenten: releasepagina in de wiki
- Voor SSC: upgradehandleiding, values-wijzigingen, gemeentespecifieke punten, `images-{version}.yaml`
