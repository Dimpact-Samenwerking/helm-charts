# Upgrade guide: PodiumD 4.7.1 → 4.7.2

## Changes

### Keycloak 26.6.1 → 26.6.2 (security release)

Upstream Keycloak 26.6.2 ships fixes for a substantial set of CVEs,
including several account-takeover-class issues. Both the Keycloak
server image and the keycloak-operator image are bumped to `26.6.2`
with refreshed digests; the operator chart (Adfinis 1.11.4) is
unchanged.

CVEs addressed:

- CVE-2026-7504 — Redirect URI validation bypass
- CVE-2026-7507 — OIDC session fixation leading to account takeover
- CVE-2026-7571 — Access token disclosure / implicit-flow bypass via
  forged client data
- CVE-2026-37982 — Execute-actions token replay allows unauthorized
  WebAuthn credential enrollment
- CVE-2026-37979 — OIDC introspection endpoint does not enforce
  audience restriction
- CVE-2026-37978 — Cross-role PII leakage via evaluate-scopes
- CVE-2026-4630 — UMA Protection API IDOR
- CVE-2026-37981 — PII enumeration via account user lookup
- CVE-2026-33871 — HTTP/2 CONTINUATION frame flood DoS
- CVE-2026-33870 — HTTP request smuggling
- CVE-2026-4628 — UMA broken access control
- CVE-2026-37980 — Stored XSS
- Bouncy Castle cryptographic fixes

See <https://www.keycloak.org/2026/05/keycloak-2662-released>.

#### Action required

No values-file changes required for gemeenten — the chart bumps the
image tag and digest centrally. The ACR mirror must mirror the new
`quay.io/keycloak/keycloak:26.6.2` and `keycloak-operator:26.6.2`
tags + digests (see `docs/images/images-4.7.2.yaml`) before rolling
out 4.7.2 to a cluster.

### nginx-unprivileged 1.30.0 → 1.30.2 (security release)

All nginx sidecars and the apiproxy now pin
`nginxinc/nginx-unprivileged:1.30.2`. The 1.30.x stable line gained
two security fixes since 4.7.1 was cut:

- CVE-2026-42945 — "nginx Rift", critical RCE in the HTTP request
  parser, fixed in 1.30.1.
- CVE-2026-9256 — buffer overflow in `ngx_http_rewrite_module`
  (medium), fixed in 1.30.2.

#### Action required

No values-file changes. The ACR mirror must mirror the new
`nginxinc/nginx-unprivileged:1.30.2` tag and digest before rollout.

### Open Inwoner 2.1.2-rc1 → 2.1.2 (stable promotion)

Version of OIP goes from `2.1.2-rc1` to the stable `2.1.2` upstream
release.

#### Action required

No action required. The ACR mirror must mirror the new
`maykinmedia/open-inwoner:2.1.2` tag and digest.

### KISS: added Kennisbank role

Added the Kennisbank role to the KISS-client.

#### Action required

No action required.