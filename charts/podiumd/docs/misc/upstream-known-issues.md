# Upstream known issues — PodiumD 4.10.0

Defects in the upstream applications that PodiumD 4.10.0 ships, and that the
podiumd chart cannot fix. Each one was found by
[podiumd-tests](https://github.com/infonl/podiumd-tests), where a test marks it
as a known defect (`xfail`) under the ID in the first column. A test that passes
again shows that the defect is gone.

Status: checked on QA with chart 4.10.0 (podiumd-tests `full` run of
2026-10-17, rev 83; later checks are dated in the row). **None is reported
upstream yet**; the "Upstream" column names where to report it. Update a row
when it is reported, fixed or worked around.

Versions are the image tags `values.yaml` pins in 4.10.0.

## Fixed upstream, not in 4.10.0 yet

| ID | Component | What happens | Fix |
|---|---|---|---|
| open-zaak-1 | Open Zaak 1.29.3 | `DELETE` of a zaak with a resultaat answers 500, although the zaak is deleted (the ETag is recalculated for the deleted resultaat). | [open-zaak#2484](https://github.com/open-zaak/open-zaak/issues/2484), fixed in 1.31.0. Upgrade notes must include the 1.31.0 warning: documents may have lost their content; run `python src/manage.py detect_overwritten_documents`. |
| open-archiefbeheer-4 | Open Archiefbeheer 2.0.0 | A destruction list never reaches "deleted" and files no report: Open Archiefbeheer marks each zaak failed because of open-zaak-1. | Same as open-zaak-1. |
| mozilla-django-oidc-db-1 | mozilla-django-oidc-db 2.0.1 (Open Inwoner 2.4.7) | `setup_configuration` writes `group_settings` on the deprecated flat admin-OIDC config, but the login reads `groups_settings`: every admin login gives 500 `KeyError: 'groups_settings'`. | Worked around in PodiumD: use the `providers` schema with `options` (`charts/podiumd/scripts/migrate-openinwoner-admin-oidc.py`, see the 4.10.0 upgrade notes). Upstream should still fix the flat path. |

## Open

### OMC 2.3.1 — [Worth-NL/NotifyNL-OMC](https://github.com/Worth-NL/NotifyNL-OMC/issues)

| ID | What happens | Impact |
|---|---|---|
| omc-1 | OMC rejects the notifications of Open Notificaties (206 with an inner 422) because of an unknown root property, so it sends no mail. Re-checked on 2026-10-19 with Open Notificaties 1.17.0: still reproduced. | Only with OMC enabled. |

### Open Zaak 1.29.3 — [open-zaak/open-zaak](https://github.com/open-zaak/open-zaak/issues)

| ID | What happens | Impact |
|---|---|---|
| open-zaak-2 | `POST /zaken/_zoek` ignores an unknown filter (for example `inpBsn__in`) and returns all zaken, where `GET /zaken` answers 400. | A client with a typo in a filter gets every zaak it may see. |
| open-zaak-3 | The audittrail endpoints check the component `audittrails` (the app label) instead of the resource's component, so only clients with `heeft_alle_autorisaties` can read them. | Applications with scoped rights cannot read audittrails. |

### Open Archiefbeheer 2.0.0 — [maykinmedia/open-archiefbeheer](https://github.com/maykinmedia/open-archiefbeheer/issues)

| ID | What happens | Impact |
|---|---|---|
| open-archiefbeheer-2 | The reviewer can rename (`PATCH`) a destruction list while it is assigned to them. | The draaiboek leaves changes to the record manager. |
| open-archiefbeheer-3 | A review response cannot empty the archiefactiedatum ("Dit veld mag niet leeg zijn"). | A proposal to keep a zaak forever cannot be taken over. |
| open-archiefbeheer-5 | The app sends no HSTS and no `X-Content-Type-Options: nosniff`. | Set them at the ingress. |

Not tested on QA (Open Archiefbeheer is not deployed there).

### Open Notificaties 1.17.0 — [open-zaak/open-notificaties](https://github.com/open-zaak/open-notificaties/issues)

| ID | What happens | Impact |
|---|---|---|
| open-notificaties-1 | `POST /abonnement` with an unreachable callback URL answers 500 (`requests.ConnectionError` in `nrc/api/validators.py`) instead of 400. | The client gets no usable error. |

### Open Formulieren 4.0.2 — [open-formulieren/open-forms](https://github.com/open-formulieren/open-forms/issues)

| ID | What happens | Impact |
|---|---|---|
| open-formulieren-1 | An anonymous submission without name fields is registered with an initiator rol without `betrokkeneIdentificatie`; Open Zaak refuses that rol (400 `invalid-betrokkene`). | The zaak and the PDF exist, but the zaak has no initiator. |
| open-formulieren-2 | Mail is queued with `django_yubin`, but no `retry_emails` is scheduled: mail that fails during an SMTP outage is never sent. | Lost confirmation mails after an SMTP outage. |
| open-formulieren-3 | The app sends no HSTS. | Set it at the ingress. |
| open-formulieren-4 | With `wait_for_payment_to_register` on, the payment status update is skipped, so the pre-registered zaak stays `betalingsindicatie: nog_niet` after the payment. | Paid zaken look unpaid. |
| open-formulieren-5 | Question, not a defect: the ZGW registration creates the zaak before the payment, also with `wait_for_payment_to_register`. The draaiboek expects no zaak for an unpaid form. | Ask upstream whether this is intended. |

open-formulieren-2 runs only in the podiumd-tests `chaos` tier;
open-formulieren-4 and 5 need `of_wait_for_payment` in the environment profile.

### Open Inwoner 2.4.7 — [maykinmedia/open-inwoner](https://github.com/maykinmedia/open-inwoner/issues)

| ID | What happens | Impact |
|---|---|---|
| open-inwoner-1 | The admin still offers the deprecated `deactivated_on`, but it does not stop a DigiD login. | A deactivated account can still log in. |
| open-inwoner-2 | With `fetch_eherkenning_zaken_with_openzaak_120_params`, Mijn zaken lists a zaak by `nietNatuurlijkPersoon.vestigingsNummer`, but its detail page only accepts a vestiging rol and answers 404. | eHerkenning users see zaken they cannot open. |
| open-inwoner-3 | Feature request: a search without results shows fixed tips, no "did you mean". | — |

### Open Beheer 0.9.1 — [maykinmedia/open-beheer](https://github.com/maykinmedia/open-beheer/issues)

| ID | What happens | Impact |
|---|---|---|
| open-beheer-1 | The frontend sends no HSTS and no nosniff. | Set them at the ingress. |
| open-beheer-2 | The zaaktypen filter `catalogus` takes the catalogus UUID, while `catalogi/choices` offers its URL, so the list is empty. | Filtering zaaktypen by catalogus shows nothing. |

### ZAC 5.9.1 — [infonl/dimpact-zaakafhandelcomponent](https://github.com/infonl/dimpact-zaakafhandelcomponent/issues)

| ID | What happens | Impact |
|---|---|---|
| zac-1 | An expired `temporaryPersonId` is still handed out, so adding a betrokkene answers 410. #7138 only improved the error. | Adding a betrokkene fails after a while; the user must search the person again. |
| zac-2 | Creating a zaak without `startdatum` answers 500 (`NullPointerException` in `calculateDoorlooptijden`). | No validation error for API clients. |
| zac-3 | Mail is sent straight over SMTP: during an outage ZAC logs "Failed to send mail" and drops it, without a queue or retry. | Lost mails after an SMTP outage. |
| zac-4 | The readiness check includes `PabcReadinessHealthCheck`: while PABC is down ZAC leaves its Service and every page fails (IN-3177). | A PABC restart takes ZAC down. |
| zac-5 | The ZGW API client has no connect or read timeout, so stale connections hang health checks after a long Open Zaak outage. | The chart points the liveness probe at `/health/ready` with `failureThreshold: 16` so Kubernetes restarts ZAC; return to `/health/live` once ZAC has timeouts. |

zac-3 runs only in the podiumd-tests `chaos` tier.

### ITA 3.3.4 — [Interne-Taak-Afhandeling/ITA](https://github.com/Interne-Taak-Afhandeling/ITA/issues)

| ID | What happens | Impact |
|---|---|---|
| ita-1 | Mail is sent straight over SMTP: during an outage ITA logs the `SmtpException`, still answers 200 and drops the mail, without a queue or retry. | Lost forwarded mails after an SMTP outage. |
| ita-2 | The root page sends no HSTS and no nosniff. | Set them at the ingress. |

ita-1 runs only in the podiumd-tests `chaos` tier.

### KISS 3.2.0 — [Klantinteractie-Servicesysteem/KISS-frontend](https://github.com/Klantinteractie-Servicesysteem/KISS-frontend/issues)

| ID | What happens | Impact |
|---|---|---|
| kiss-1 | The BRP proxy rewrites the request body but keeps the original `Content-Length`, so a body that is not compact JSON gives 500. | KISS's own frontend sends compact JSON; other clients fail. |

### PABC 2.1.0 — [Platform-Autorisatie-Beheer-Component/PABC-API](https://github.com/Platform-Autorisatie-Beheer-Component/PABC-API/issues)

| ID | What happens | Impact |
|---|---|---|
| pabc-1 | The app sends no HSTS, no nosniff and no frame protection. | Set them at the ingress; frame protection must come from the app. |

## Security headers at the ingress

The header findings (open-archiefbeheer-5, open-formulieren-3, open-beheer-1,
ita-2, pabc-1) are best fixed upstream. Until then the ingress can add HSTS and
`X-Content-Type-Options: nosniff`: both have one possible value, so they cannot
weaken a header the app sends itself. The QA environments (podiumd-infra) do
this with a Traefik `headers` Middleware; SSC needs the equivalent on its
ingress. Frame protection (`X-Frame-Options`, CSP `frame-ancestors`) must come
from the app: an ingress value would replace the app's own.

## Not upstream

These findings from the same review are PodiumD's own and are tracked in the
chart or the environments, not here: podiumd-chart-3 (resource requests),
podiumd-chart-5 (admin login on the old objecttypen host), podiumd-chart-8
(PodDisruptionBudgets, IN-3178), kiss-2 (Logboek token permission in the
reference configuration), and the ExternalsPodiumD questions
(externalspodiumd-1, externalspodiumd-2).
