# Portaal — PodiumD 4.8

← [Terug naar PodiumD 4.8 overzicht](podiumd-4.8.md)

| | |
|---|---|
| Component | Portaal |
| Gemaakt door | Maykin Media |
| Vorige app versie | 2.1.2 |
| Vorige chart versie | 2.1.3 |
| Huidige app versie | 2.3.0 |
| Huidige chart versie | 2.2.0 |
| Bijgewerkt (datum) | — |

## Wijzigingen

**⇧ Minor update** (overspant 2.2.0 en 2.3.0)

### 🚀 New functionality

- Bestandsuploads optioneel gescand op virussen via ClamAV (opt-in via siteconfiguratie; ClamAV daemon vereist)
- Gebruikers ontvangen automatisch e-mailnotificaties als contactuitnodigingen worden geaccepteerd
- Lijstondersteuning toegevoegd in FAQ- en vragenlijststappen
- ZGW-cache wordt bij inloggen vooraf geladen via Celery (verbeterde laadtijd Mijn Zaken)
- Elasticsearch ondersteunt nu HTTP Basic Auth (`ES_USERNAME` / `ES_PASSWORD`)
- BRP API: configureerbare versie-ondersteuning (1.3, 2.0–2.7) via admin, vervangt `BRP_VERSION` env-var

### ✅ Improvements

- ZGW-cache timeout verhoogd van 60s naar 300s (nieuwe standaard: `CACHE_ZGW_ZAKEN_TIMEOUT`)
- Zaaklijst laadt sneller via pagineerbare datafetch
- Overbodige API-aanroepen bij bijwerken van digitale adressen teruggebracht
- Documenttitels tonen geen bestandsextensie meer
- WCAG-toegankelijkheidsverbeteringen (rapport Enschede)
- Django bijgewerkt naar 5.2; Python naar 3.13
- Django CMS v3 → v4 migratie (eenmalig; vereist `manage.py cms4_migration` — zie deploymentnotities)

### 🐞 Bug fixes

- Formulieren gebruiken nu `vervolg_link` in plaats van de zaakdetail-URL
- Zaakstatus werkt correct bij wijzigingen zonder URL-verandering in de backend
- Lange bestandsnamen in notificaties worden nu correct afgekapt
- Mijn Zaken hangt niet meer op een spinner als er een fout optreedt
- SSL-certificaatvalidatie voor Haal Centraal BRP API hersteld
- Admin crashed bij grote gebruikersdatasets (laadt keuzesets nu on-demand)
- DigiD-gebruikers worden na uitloggen correct doorgestuurd als OIDC uitgeschakeld is
- eHerkenning: gebruikers met vestigingen ontvangen nu zowel KVK- als vestigingsnummer
- Cache-sleutel voor `fetch_zaak_roles` bevat nu `betrokkene_type` (foute rolkoppeling opgelost)
- E-mailsjabloonopmaak bleef niet behouden na Prosemirror-migratie (2.0.0 regressie)
- Betrokkene-rolverificatie verbeterd voor zaaktoegangscontrole
- Zaakstatusnotificaties tonen omschrijving correct (niet meer als HTML)

### 🔏 Security fixes

- Dependency-updates: pyopenssl, cbor2, cryptography, urllib3, PyJWT, cssnano, immutable, vite, lodash, typing-extensions

### 🔐 Fixes CVEs

| CVE | Severity | Summary |
|---|---|---|
| CVE-2026-29074 | — | cssnano kwetsbaarheid; opgelost via update |
| CVE-2026-29063 | — | immutable kwetsbaarheid; opgelost via update |
| CVE-2026-32597 | — | PyJWT kwetsbaarheid; opgelost via update naar 2.10.1 |
| CVE-2026-39364 | — | vite kwetsbaarheid; opgelost via update naar 7.3.2 |
| CVE-2026-4800 | — | vite kwetsbaarheid; opgelost via update naar 7.3.2 |

### 📗 Further details

[Open Inwoner changelog v2.2.0](https://docs.openinwoner.nl/en/v2.2.0/changelog.html)
[Open Inwoner changelog v2.3.0](https://docs.openinwoner.nl/en/v2.3.0/changelog.html)
