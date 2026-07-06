# PodiumD 4.8 — Releaseoverzicht

| | |
|---|---|
| PodiumD versie | 4.8.0 |
| Gestart week | 25/2026 |
| Acceptatie week | 29/2026 |
| Status | building |
| Bijgewerkt (datum) | - |

---

## Doelgroep

Dit document is bestemd voor functioneel applicatiebeheer. Zie [`UPGRADING.md`](../UPGRADING.md) en [`upgrade-from-4.7.6-to-4.8.0.md`](../upgrade-from-4.7.6-to-4.8.0.md) voor de technische upgrade-instructies.

---

## Producten

Gebruikersgerichte applicaties die direct door eindgebruikers of medewerkers worden bediend.

| Component | Gemaakt door | Versie 4.7 - App | Versie 4.7 - Chart | Versie 4.8 - App | Versie 4.8 - Chart | Wijzigingen |
|---|---|---|---|---|---|---|
| Formulier | Maykin Media | 3.4.9 | 1.12.0 | 3.4.10 | 1.12.0 | [🟦 Patch update](podiumd-4.8-formulier-3.4.10.md) |
| Portaal | Maykin Media | 2.1.2 | 2.1.3 | 2.3.0 | 2.2.0 | [⇧ Minor update](podiumd-4.8-portaal-2.3.0.md) |
| Contact | ICATT Menselijk Digitaal | 2.2.2 | 2.2.2 | 2.2.3 | 2.2.2 | [🟦 Patch update](podiumd-4.8-contact-2.2.3.md) |
| Interne Taak Afhandeling | ITA project | 3.1.0 | 3.1.0 | 3.2.0 | 3.2.0 | [⇧ Minor update](podiumd-4.8-ita-3.2.0.md) |
| Zaak - ZAC | INFO.nl | 4.7.2 | 1.0.228 | 5.0.1 | 1.0.251 | [⇪ Major update](podiumd-4.8-zac-5.0.1.md) |
| Zaak - Archiefbeheer | Maykin Media | 2.0.0 | 2.0.0 | 2.0.0 | 2.0.0 | [🟩 Geen update](podiumd-4.8-archiefbeheer-2.0.0.md) |
| Zaak - ZGW Office Add-in | INFO.nl | v0.9.313 | 0.0.88 | v0.9.313 | 0.0.89 | [🟩 Geen update](podiumd-4.8-zgw-office-addin-v0.9.313.md) |

---

## Common Ground componenten

Backend-componenten die de Common Ground API-standaarden implementeren en door meerdere producten worden gedeeld.

| Component | Gemaakt door | Versie 4.7 - App | Versie 4.7 - Chart | Versie 4.8 - App | Versie 4.8 - Chart | Wijzigingen |
|---|---|---|---|---|---|---|
| Open Zaak | Maykin Media | 1.27.2 | 1.14.1 | 1.27.2 | 1.14.1 | [🟩 Geen update](podiumd-4.8-openzaak-1.27.2.md) |
| Open Klant | Maykin Media | 2.15.0 | 1.11.0 | 2.15.0 | 1.11.0 | [🟩 Geen update](podiumd-4.8-openklant-2.15.0.md) |
| Objecten API | Maykin Media | 3.6.0 | 2.12.0 | 3.6.0 | 2.12.0 | [🟩 Geen update](podiumd-4.8-objecten-3.6.0.md) |
| Objecttypen API | Maykin Media | 3.4.2 | 1.6.1 | 3.4.2 | 1.6.1 | [🟩 Geen update](podiumd-4.8-objecttypen-3.4.2.md) |
| Open Notificaties | Maykin Media | 1.15.0 | 1.13.1 | 1.16.0 | 2.0.0 | [⇧ Minor update](podiumd-4.8-opennotificaties-1.16.0.md) |
| Platform Autorisatie Beheer Component (PABC) | Dimpact | 1.1.0 | 1.1.0 | 1.1.0 | 1.1.0 | [🟩 Geen update](podiumd-4.8-pabc-1.1.0.md) |
| Open Beheer (LBI) | Maykin Media | 0.9.0 | 0.1.3 | 0.9.0 | 0.1.3 | [🟩 Geen update](podiumd-4.8-openbeheer-0.9.0.md) |
| Referentielijst | Maykin Media | 0.7.2 | 0.1.1 | 0.7.3 | 0.1.1 | [🟦 Patch update](podiumd-4.8-referentielijst-0.7.3.md) |
| OMC / Notify | Worth IT | 1.17.19 | 0.14.1 | 1.17.19 | 0.14.1 | [🟩 Geen update](podiumd-4.8-omc-1.17.19.md) |
| Zaakbrug | WeAreFrank | 1.26.13 | 2.3.26 | 1.26.14 | 2.3.27 | [🟦 Patch update](podiumd-4.8-zaakbrug-1.26.14.md) |
| Frank Gateway | WeAreFrank | — | — | — | — | _Niet in PodiumD chart_ |

---

## Ondersteunende componenten

Platform- en infrastructuurcomponenten die de producten en Common Ground componenten faciliteren.

| Component | Gemaakt door | Versie 4.7 - App | Versie 4.7 - Chart | Versie 4.8 - App | Versie 4.8 - Chart | Wijzigingen |
|---|---|---|---|---|---|---|
| Keycloak | Red Hat | 26.6.3 | 1.12.0 | 26.6.3 | 1.12.0 | [🟩 Geen update](podiumd-4.8-keycloak-26.6.3.md) |
| ClamAV | ClamAV project | 1.4.4 | 3.7.1 | 1.4.4 | 3.7.1 | [🟩 Geen update](podiumd-4.8-clamav-1.4.4.md) |
| Kiss-elastic (ECK) | Elastic | 8.19.3 | 1.1.0 | 8.19.3 | 1.1.0 | [🟩 Geen update](podiumd-4.8-kisselastic-8.19.3.md) |
| Redis (operator + cluster) | Opstree | v8.6.2 | 0.24.0 | v8.6.2 | 0.25.0 | [🟦 Patch update](podiumd-4.8-redis-v0.25.0.md) |
| Nginx (nginx-unprivileged) | NGINX Inc. | 1.30.2 | — | 1.31.1 | — | [⇧ Minor update](podiumd-4.8-nginx-1.31.1.md) |

---

## Technische componenten

Overige componenten die niet in de bovenstaande categorieën vallen, zoals testfaciliteiten, hulpimages en interne adapters.

| Component | Gemaakt door | Versie 4.7 - App | Versie 4.7 - Chart | Versie 4.8 - App | Versie 4.8 - Chart | Wijzigingen |
|---|---|---|---|---|---|---|
| API Proxy (APISIX) | Apache | 3.16.0-ubuntu | 2.14.0 | 3.16.0-ubuntu | 2.14.0 | [🟩 Geen update](podiumd-4.8-apisix-3.16.0.md) |
| BRP Personen Mock | Haal Centraal | 2.7.0-202508211438 | 1.2.8 | 2.7.0-202606230850 | 1.2.9 | [🟦 Patch update](podiumd-4.8-brp-personen-mock-2.7.0.md) |
| Podiumd Adapter (MI) | ICATT Menselijk Digitaal | 0.6.6 | — | 0.6.6 | — | [🟩 Geen update](podiumd-4.8-podiumd-adapter-0.6.6.md) |
| Keycloak Config CLI | adorsys | 6.5.0-26 | — | 6.5.1-26 | — | [🟦 Patch update](podiumd-4.8-keycloak-config-cli-6.5.1-26.md) |
| alpine/k8s (redis-ha init) | Alpine Linux | 1.34.7 | — | 1.36.2 | — | [⇧ Minor update](podiumd-4.8-alpine-k8s-1.36.2.md) |
| Python (KC PBKDF2 init) | Python project | 3.12-slim | — | 3.14-slim | — | [⇧ Minor update](podiumd-4.8-python-3.14-slim.md) |
| Gotenberg (ZAC) | Gotenberg | 8.31.0 | — | 8.33.0 | — | [⇧ Minor update](podiumd-4.8-gotenberg-8.33.0.md) |
| Open Policy Agent (ZAC) | OPA project | 1.15.2-static | — | 1.17.1-static | — | [⇧ Minor update](podiumd-4.8-opa-1.17.1-static.md) |
| Solr (ZAC) | Apache | 9.10.1-slim | — | 9.10.1-slim | — | [🟩 Geen update](podiumd-4.8-solr-9.10.1-slim.md) |
| Busybox (ZAC Solr init) | BusyBox | 1.37.0-glibc | — | 1.38.0-glibc | — | [⇧ Minor update](podiumd-4.8-busybox-1.38.0-glibc.md) |
