# Security response headers (IN-3162)

PodiumD's smoke tests (podiumd-tests `tests/smoke/test_web_security.py`) check
that every app root sends three protections on its HTML pages:

| Header | Protects against | Where it belongs |
| --- | --- | --- |
| `Strict-Transport-Security` (HSTS) | downgrade to plain HTTP, cookie theft over HTTP | the edge, where TLS terminates |
| `X-Content-Type-Options: nosniff` | the browser guessing a content type (MIME sniffing) | the app; the edge as a safety net |
| `X-Frame-Options` or CSP `frame-ancestors` | clickjacking (the page loaded in a hostile iframe) | only the app |

## What the edge does

Since 4.10.0 every route sets HSTS (`max-age=31536000`) and nosniff, with a
`ResponseHeaderModifier` on each HTTPRoute rule of NGINX Gateway Fabric.
`set` replaces a value the app sends itself, so a header is never sent twice.
Both headers have only one meaningful value for these apps, so the edge does
not weaken anything an app sends. The routes are deploy-side
(`ssl-gateway.yml` per environment), not in the podiumd chart; add the filter
with
[`migrate-gateway-security-headers.py`](../../scripts/migrate-gateway-security-headers.py),
see the [4.10.0 upgrade guide](../_UPGRADE_PATHS/4.9.5-to-4.10.0-upgrade.md#security-headers-at-the-edge-in-3162).

The edge deliberately sets no `X-Frame-Options` and no CSP: some apps are
embedded in an iframe (Open Formulieren in Open Inwoner), and an edge value
would replace the app's own policy. Only the app can decide whether it may be
framed.

## What the apps send themselves

Measured on QA (4.10.0, 19 October 2026) inside the cluster, so without the
edge; OMC and Open Archiefbeheer from the check on 15 October.

| App | Vendor | nosniff | Frame protection | Needs a vendor fix |
| --- | --- | --- | --- | --- |
| PABC | Dimpact / ICATT (.NET) | no | no | nosniff and frame protection; **high**: an admin app that can be framed |
| ITA | ICATT (.NET) | no | n/a (login redirect) | nosniff |
| OMC (NotifyNL) | Worth Systems (.NET) | no | n/a (API) | nosniff |
| Open Archiefbeheer | Maykin | no (frontend) | yes | nosniff on the frontend |
| Open Beheer 0.9.1 | Maykin | no (frontend) | yes (`DENY`, `frame-ancestors 'none'`) | nosniff on the frontend |
| Open Formulieren | Maykin | yes | yes | none |

HSTS is not asked of vendors: it belongs at the edge, and Maykin leaves it to
the reverse proxy on purpose.

## Vendor ticket texts

Drafts to file with each vendor. They are not filed yet; whoever files one adds
the link to IN-3162.

### PABC (PodiumD Autorisatie Beheer Component)

> **Title:** Send `X-Content-Type-Options: nosniff` and frame protection
>
> PABC's web pages are sent without `X-Content-Type-Options` and without
> `X-Frame-Options` or a `Content-Security-Policy` `frame-ancestors`
> directive. Measured on PABC 2.1.0 (PodiumD 4.10.0): `GET /` with
> `Accept: text/html` returns `200` with only `Content-Type: text/html`.
>
> PABC is an administration application: it manages who may do what in
> ZAC and the other PodiumD apps. A page that any other site may load in an
> iframe allows clickjacking, where a user is tricked into clicking buttons
> in an invisible PABC page while logged in.
>
> Please add, to every response (for example with an ASP.NET Core
> middleware):
>
> - `X-Content-Type-Options: nosniff`
> - `Content-Security-Policy: frame-ancestors 'self'` (or `'none'` when PABC
>   is never framed), optionally also `X-Frame-Options: SAMEORIGIN` for old
>   browsers.
>
> HSTS is not needed in the application: the PodiumD edge sets it, and it
> also sets nosniff as a safety net. Frame protection cannot be set at the
> edge, because only the application knows whether it may be framed.

### ITA (Interne Taak Afhandeling)

> **Title:** Send `X-Content-Type-Options: nosniff`
>
> ITA's responses have no `X-Content-Type-Options` header (ITA in PodiumD
> 4.10.0). Without it, a browser may guess a response's content type
> (MIME sniffing) and, for example, run user-supplied content as script.
>
> Please add `X-Content-Type-Options: nosniff` to every response, for
> example with an ASP.NET Core middleware. The PodiumD edge sets it as a
> safety net and also sets HSTS, but each hosting party has to remember
> that; the application is the right place.

### OMC (NotifyNL Output Management Component)

> **Title:** Send `X-Content-Type-Options: nosniff`
>
> OMC's responses have no `X-Content-Type-Options` header (OMC 2.3.1 in
> PodiumD 4.10.0). Please add `X-Content-Type-Options: nosniff` to every
> response, for example with an ASP.NET Core middleware. It prevents a
> browser from guessing the content type of a response (MIME sniffing).
> The PodiumD edge sets it as a safety net, but each hosting party has to
> remember that.

### Open Archiefbeheer

> **Title:** Frontend: send `X-Content-Type-Options: nosniff`
>
> The Open Archiefbeheer frontend (the SPA served by its nginx) sends no
> `X-Content-Type-Options` header; the Django backend does. Please add to
> the frontend's nginx configuration:
>
> ```nginx
> add_header X-Content-Type-Options nosniff always;
> ```
>
> Frame protection is already there. HSTS is left to the reverse proxy, as
> before.

### Open Beheer

> **Title:** Frontend: send `X-Content-Type-Options: nosniff`
>
> The Open Beheer frontend (0.9.1) sends `X-Frame-Options: DENY` and a
> `Content-Security-Policy` with `frame-ancestors 'none'`, but no
> `X-Content-Type-Options`. Please add to the frontend's nginx
> configuration:
>
> ```nginx
> add_header X-Content-Type-Options nosniff always;
> ```
>
> HSTS is left to the reverse proxy, as before.

## Follow-up in podiumd-tests

Once every test environment has the edge headers, the non-strict xfails in
`test_web_security.py` go. One `strict=True` xfail stays for PABC's frame
protection, pointing to the PABC ticket, until PABC ships the fix.
