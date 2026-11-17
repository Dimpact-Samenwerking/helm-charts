# Frank!Gateway — client certificates through the Azure Application Gateway

Design note for the hosting partner (SSC-Hosting) and the PodiumD team. How a
client certificate presented by an external party reaches the Frank!Gateway
inway when an Azure Application Gateway (AAG) fronts the environment, what
each component checks, and what the hosting partner configures. The chart side
is described in
[`frankgateway-routes.md`](frankgateway-routes.md#consumer-identities-from-openbao-inbound);
the process for a gemeente is in the TSA guide
[`frankgateway-tsa-setup-and-flow-NL.md`](frankgateway-tsa-setup-and-flow-NL.md).

| | |
|---|---|
| Status | Decided 2026-10-29 (IN-3287); tested on ontw-dim1 on 2026-11-04 and 2026-11-05 ([`frankgateway-aag-test-round-ontw-dim1.md`](frankgateway-aag-test-round-ontw-dim1.md)) |
| Tracked in | IN-3287 (decision), IN-3372 (ontw-dim1), IN-2818 (header contract), DS-6618 (SSC side) |
| Replaces | the verify-mode proposal written for IN-2658, which was never merged |
| Applies to | inway class only (`frankgateway.instances.inway`) |

## Short answer

The Application Gateway is a terminating proxy: it cannot pass TLS through, so
Frank!Gateway never sees the client's TLS session. The AAG therefore
terminates TLS, **requests** the client certificate in passthrough mode
without validating it, and forwards it as request headers on the API listener
only. The inway authorises the caller on the certificate's SHA-1 fingerprint
against a consumer list in OpenBao and the route's `allow` list.

No CA is managed anywhere. A fingerprint names one exact certificate and the
TLS handshake at the AAG proves the caller holds its private key, so a chain
check would add CA administration without adding authentication.

## What the hosting partner configures

Once per environment, on the existing AAG. Nothing per external party, per
certificate or per CA.

| # | Action | Why |
|---|---|---|
| 1 | An HTTPS listener for the API hostname with an SSL profile in mutual-authentication **passthrough** mode, and the environment's server certificate with that hostname | the client certificate is requested on exactly this hostname and on no other |
| 2 | A rewrite rule set on that listener's routing rule that writes `X-Client-Cert`, `X-Client-Cert-Fingerprint`, `X-Client-Cert-Subject` and `X-Client-Cert-Issuer` from the `client_certificate` server variables | the identity the inway authorises on; set from server variables, so a value the caller sends is always replaced |
| 3 | The same four headers removed on every other listener | a caller can never supply them on another hostname |
| 4 | The backend hop unchanged: HTTPS 443 to NGINX Gateway Fabric with the public hostname as SNI | the terminate-and-re-encrypt hop that already exists |

The exact format of the headers as the inway receives them is in
[routes → what the front door must send](frankgateway-routes.md#what-the-front-door-must-send).

## What is checked where

| Check | Where | Note |
|---|---|---|
| The caller holds the private key of the certificate | AAG, TLS handshake | a certificate with the wrong key never completes the handshake |
| Issuing CA and chain | nowhere, by design | any CA is forwarded; the fingerprint list decides |
| Validity period | nowhere on chart 4.10.x | the AAG forwards an expired certificate; the inway gets its own check with IN-3445 (PodiumD 4.10.2, decided on IN-3411). Until then an expired but registered certificate is admitted |
| Key usage (EKU) | nowhere | a server-only certificate is forwarded; registering one is the registrar's decision |
| Revocation | inway, by removal | there is no CRL or OCSP on the path; removing the fingerprint from OpenBao is the revocation |
| Which consumer this is | inway | fingerprint against `frankgateway/consumers` in OpenBao |
| Whether the consumer may use this route | inway | the route's `allow` list |
| What the consumer may do | the register behind the route | its own authorisation on the caller's API token |

## Why the headers can be trusted

A header is proof of identity only if nobody else can write it. Two
properties make that hold:

- **The AAG replaces the headers on every request.** A caller who sends
  `X-Client-Cert-Fingerprint` without a certificate arrives with no such
  header and gets 401; a caller who sends it next to another certificate
  arrives with that certificate's real fingerprint (measured, B5 and B6).
- **The inway is reachable only through the AAG.** The inway's NetworkPolicy
  admits the NGF data-plane namespace only
  (`networkPolicies.ingressNamespace`), and the chart refuses to render an
  `openbao-consumer-auth` route while the policies are off or on any class
  other than `inway`.

The headers stop being proof the moment the API hostname is reachable through
a second front door that does not replace them.

## Outcomes

Measured on ontw-dim1 through the AAG.

| Situation | Decided by | Result |
|---|---|---|
| Registered certificate, consumer in the route's `allow` | inway | 200; the upstream receives `X-Consumer-Username`, the access log carries `consumer` |
| Registered certificate, consumer not in `allow` | inway | 403 `consumer_not_allowed` |
| Certificate that is not registered: known CA, unknown CA, expired or server-only | inway | 401 `unknown_client_certificate` |
| No client certificate | inway | 401 `client_certificate_required` |
| Forged `X-Client-Cert-*` header | AAG replaces it, inway decides | as if the header had not been sent |
| Certificate with the wrong private key | TLS | no connection |
| Fingerprint added to or removed from OpenBao | inway cache | live on every worker within 300 s from PodiumD 4.10.1; on 4.10.0 only after a restart of the gateway pods (IN-3417) |
| OpenBao unreachable | inway | the last-good list is served up to `stale_ttl` (3600 s), then 503. Not measured in the test round |

## Restrictions and open points

| Where | Restriction or open point | Consequence |
|---|---|---|
| AAG | Cannot pass TLS through | Frank!Gateway cannot read the certificate from the TLS session; it relies on the headers |
| AAG | The fingerprint server variable is SHA-1 | consumer entries in OpenBao are SHA-1 fingerprints. It is an identifier here, not a signature |
| AAG | Forwards the leaf certificate only, also when the client sends a chain | no chain validation is possible at the inway, and none is wanted |
| AAG | Checks nothing about the certificate in passthrough mode | the consumer list is the only gate; see the validity period above |
| AAG | A listener per API hostname; SSC reports the production gateway close to its listener limit (DS-6618) | to be resolved by SSC before the roll-out to further environments |
| AAG | The removal of the headers on the other listeners cannot be observed from outside | it rests on SSC's configuration |
| NGF | The hop from NGF to the inway was plain HTTP on ontw-dim1 | whether this hop is re-encrypted is an open point with SSC (DS-6618); the headers arrive unchanged either way |
| Inway | The OpenBao cache is per nginx worker, 300 s | for up to 300 s after a write, old and new answers alternate |

## The alternatives, and why not

- **Verify (strict) mode on the AAG.** The AAG would validate the chain and
  refuse an untrusted certificate itself. It needs every gemeente's issuing CA
  uploaded at SSC, makes each CA change a ticket, and adds no authentication
  on top of the fingerprint match.
- **TLS passthrough or a TCP listener**, so that Frank!Gateway terminates TLS
  itself. Not available on the Application Gateway for this traffic, or it
  loses the WAF and the HTTP routing of the AAG.
- **A CA check in the inway on top of the fingerprint.** No extra
  authentication, extra CA administration in OpenBao, and impossible in
  practice now that only the leaf is forwarded.

## Where this stands

The path was exercised on ontw-dim1 with a test PKI; the matrix and the
results are in
[`frankgateway-aag-test-round-ontw-dim1.md`](frankgateway-aag-test-round-ontw-dim1.md).
It has not run for a gemeente yet. Still to come: the validity check in the
inway (IN-3445, PodiumD 4.10.2) and the roll-out to the test and acceptance environments of
Enschede (IN-3428).
