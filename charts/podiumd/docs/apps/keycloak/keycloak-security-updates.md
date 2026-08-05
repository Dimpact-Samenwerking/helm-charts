# Keycloak Security Updates

This document logs all security-relevant settings for Keycloak realms managed by this chart.
Each entry records: what the setting is, its current/target value, why it matters, what standard or
guideline applies, and how it is implemented (chart default, realm import, or environment override).

Settings that are already at a secure default are logged for audit purposes but require no change.

## Standards reference

| Abbreviation | Full name | Status for Dutch government |
|---|---|---|
| **BIO 2.0** | Baseline Informatiebeveiliging Overheid 2.0 (gebaseerd op NEN-EN-ISO/IEC 27002:2022) | Verplicht (verplichtende zelfregulering per sept 2025, wettelijk via Cyberbeveiligingswet) |
| **Forum / HTTPS+HSTS** | Forum Standaardisatie: HTTPS en HSTS (RFC 9110 + RFC 6797) | **Wettelijk verplicht** per 1 juli 2023 (Besluit beveiligde verbinding met overheidswebsites en -webapplicaties, Wet digitale overheid) |
| **Forum / OAuth NL GOV** | Forum Standaardisatie: NL GOV Assurance Profile for OAuth 2.0 (Logius) | Verplicht ('Pas toe of leg uit') |
| **Forum / OpenID NLGov** | Forum Standaardisatie: Authenticatie-standaarden (OpenID.NLGov en SAML) (Logius) | Verplicht ('Pas toe of leg uit') |
| **NCSC Webapplicaties** | NCSC ICT-beveiligingsrichtlijnen voor webapplicaties | Aanbevolen (richtlijn) |
| **NIST SP 800-63B** | NIST Digital Identity Guidelines — Authentication and Lifecycle Management | Internationaal referentiekader; BIO 2.0 sluit hierop aan |
| **NIS2 / Cbw** | NIS2-richtlijn (EU 2022/2555), geïmplementeerd als Cyberbeveiligingswet (Cbw, in werking 2025) — artikel 21 risicobeheermaatregelen | Wettelijk verplicht voor aanbieders van essentiële en belangrijke diensten |
| **OWASP ASVS 4.0** | OWASP Application Security Verification Standard 4.0 — Level 2 (Standard) | Internationaal aanbevolen; vult BIO 2.0 aan voor applicatiebeveiliging |
| **RFC 9700** | OAuth 2.0 Security Best Current Practice (BCP) — vervangt RFC 6819 | Verplicht referentiekader voor OAuth 2.0 implementaties; onderdeel van Forum / OAuth NL GOV |

## Master Realm

### Browser Security Headers

| Setting | Value | Status |
|---------|-------|--------|
| `xContentTypeOptions` | `nosniff` | ✅ Configured |
| `xRobotsTag` | `none` | ✅ Configured |
| `xFrameOptions` | `SAMEORIGIN` | ✅ Configured |
| `contentSecurityPolicy` | `frame-src 'self'; frame-ancestors 'self'; object-src 'none';` | ✅ Configured |
| `xXSSProtection` | `1; mode=block` | ✅ Configured |
| `strictTransportSecurity` | `max-age=31536000; includeSubDomains` | ✅ Configured (was empty) |

**`xContentTypeOptions: nosniff`**
- **Standard:** NCSC Webapplicaties — sectie Transport/Responsheaders; BIO 2.0 / ISO 27002:2022 maatregel 8.23
- **Why:** Prevents MIME-type sniffing attacks where browsers interpret files as a different content type.

**`xFrameOptions: SAMEORIGIN`**
- **Standard:** NCSC Webapplicaties — sectie Clickjacking; BIO 2.0 / ISO 27002:2022 maatregel 8.23
- **Why:** Prevents the admin console from being embedded in an iframe on a foreign domain (clickjacking).

**`contentSecurityPolicy`**
- **Standard:** NCSC Webapplicaties — sectie Content Security Policy; BIO 2.0 / ISO 27002:2022 maatregel 8.23
- **Why:** Restricts which origins can embed the page and blocks object/plugin execution, reducing XSS and injection attack surface.

**`strictTransportSecurity: max-age=31536000; includeSubDomains`** ← changed from empty
- **Standard:** **Forum / HTTPS+HSTS** — RFC 6797; wettelijk verplicht per 1 juli 2023 (Wet digitale overheid); NCSC Webapplicaties — sectie HTTPS/HSTS
- **Why:** Without HSTS, browsers may downgrade to HTTP after the first visit. Keycloak sets this header on all its responses; an empty value means no HSTS is sent even though TLS is used at the ingress.
- **Implementation:** `keycloak-master-realm-config.yaml` → `browserSecurityHeaders.strictTransportSecurity`

### Brute Force Protection

| Setting | Current value | Keycloak default | Status |
|---------|--------------|-----------------|--------|
| `bruteForceProtected` | `true` | `false` | ✅ Configured (was false) |
| `failureFactor` | `5` | `30` | ✅ Configured (was 30) |
| `permanentLockout` | `false` | `false` | ✅ Default — temporary lockout preferred |
| `maxFailureWaitSeconds` | `900` (15 min) | `900` | ✅ Default acceptable |
| `waitIncrementSeconds` | `60` | `60` | ✅ Default acceptable |
| `minimumQuickLoginWaitSeconds` | `60` | `60` | ✅ Default acceptable |
| `quickLoginCheckMilliSeconds` | `1000` | `1000` | ✅ Default acceptable |
| `maxDeltaTimeSeconds` | `43200` (12 h) | `43200` | ✅ Default acceptable |

**`bruteForceProtected: true`** ← changed from false
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.5** (Beveiligde authenticatie); NCSC Webapplicaties — sectie Authenticatie (begrens inlogpogingen); NIST SP 800-63B §5.2.2; **OWASP ASVS 4.0 V2.2.1** (vereist rate-limiting of lockout na herhaalde mislukte pogingen)
- **Why:** Without brute force protection there is no lockout on failed login attempts. An attacker can make unlimited password guesses against the admin console.
- **Implementation:** `keycloak-master-realm-config.yaml` → `bruteForceProtected: true`

**`failureFactor: 5`** ← changed from 30
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.5**; NIST SP 800-63B §5.2.2 (recommends throttling after a small number of consecutive failures); NCSC Webapplicaties — sectie Authenticatie; **OWASP ASVS 4.0 V2.2.1**
- **Why:** 30 failed attempts is far too permissive. 5 consecutive failures is the widely accepted threshold before a temporary lockout is imposed.
- **Implementation:** `keycloak-master-realm-config.yaml` → `failureFactor: 5`

### Password Policy

| Setting | Value | Status |
|---------|-------|--------|
| `passwordPolicy` | `length(14) and notUsername(undefined) and notEmail(undefined) and passwordHistory(5)` | ✅ Configured (was empty) |

**`passwordPolicy`** ← changed from empty
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **5.17** (Authenticatie-informatie); NIST SP 800-63B §5.1.1; **OWASP ASVS 4.0 V2.1.1**
- **Why:** Admin accounts for the master realm have elevated privileges (full Keycloak administration). The password policy uses a stricter minimum length of 14 characters vs. 12 for the podiumd realm, reflecting the higher risk of admin account compromise. Complexity rules (uppercase, special chars) are deliberately omitted per NIST SP 800-63B §5.1.1 guidance.
  - `length(14)` — minimum 14 characters (stricter than podiumd; admin accounts warrant higher bar)
  - `notUsername` — cannot use the username as the password
  - `notEmail` — cannot use the email address as the password
  - `passwordHistory(5)` — prevents reuse of the last 5 passwords
- **Implementation:** `keycloak-master-realm-config.yaml` → `passwordPolicy`

### Token Lifespans

| Setting | Current value | Keycloak default | Status |
|---------|--------------|-----------------|--------|
| `accessTokenLifespan` | `60` s (1 min) | `300` s | ✅ More restrictive than default — good |
| `accessTokenLifespanForImplicitFlow` | `900` s (15 min) | `900` s | ✅ Default |
| `ssoSessionIdleTimeout` | `1800` s (30 min) | `1800` s | ✅ Default — acceptable for admin use |
| `ssoSessionMaxLifespan` | `36000` s (10 h) | `36000` s | ✅ Default — acceptable for admin use |
| `clientSessionIdleTimeout` | `0` (inherits SSO) | `0` | ✅ Default |
| `clientSessionMaxLifespan` | `0` (inherits SSO) | `0` | ✅ Default |
| `offlineSessionIdleTimeout` | `2592000` s (30 d) | `2592000` s | ✅ Default |
| `offlineSessionMaxLifespanEnabled` | `false` | `false` | ✅ Default |
| `actionTokenGeneratedByUserLifespan` | `300` s (5 min) | `300` s | ✅ Default |
| `actionTokenGeneratedByAdminLifespan` | `43200` s (12 h) | `43200` s | ✅ Default |

**`accessTokenLifespan: 60`**
- **Standard:** **Forum / OAuth NL GOV** — vereist korte token levensduur voor access tokens; BIO 2.0 / ISO 27002:2022 maatregel **8.5**; NIST SP 800-63B §7.1
- **Why:** Short-lived access tokens limit the window of exposure if a token is stolen. 60 s is already more restrictive than Keycloak's default of 300 s.
- **Status:** No change needed — already correctly configured.

**`ssoSessionIdleTimeout: 1800` / `ssoSessionMaxLifespan: 36000`**
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.5**; NCSC Webapplicaties — sectie Sessiebeheer (stel sessietime-out in)
- **Why:** Sessions must expire after inactivity to prevent session hijacking from unattended terminals. 30 min idle / 10 h max is acceptable for an admin console.
- **Status:** No change needed — defaults are acceptable.

### Refresh Token Rotation

| Setting | Current value | Keycloak default | Status |
|---------|--------------|-----------------|--------|
| `revokeRefreshToken` | `true` | `false` | ✅ Configured (was false) |
| `refreshTokenMaxReuse` | `0` | `0` | ✅ Default |

**`revokeRefreshToken: true`** ← changed from false
- **Standard:** **Forum / OAuth NL GOV** (Logius NL GOV Assurance Profile for OAuth 2.0) — vereist gebruik van refresh token rotation om hergebruik te detecteren; RFC 9700 (OAuth 2.0 Security BCP) §2.2.2
- **Why:** Each refresh token may only be used once. If a stolen refresh token is replayed after the legitimate client already used it, Keycloak detects the duplicate use and revokes the entire session — providing theft detection.

### OTP / MFA

| Setting | Value | Status |
|---------|-------|--------|
| `adminOtpEnabled` (chart value) | `true` | ✅ Configured — TOTP `CONFIGURE_TOTP` set as default required action |

**OTP enforcement via `CONFIGURE_TOTP` required action**
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.5** (Beveiligde authenticatie) — vereist MFA voor beheerderstoegang; **Forum / OpenID NLGov** — authenticatiebetrouwbaarheidsniveau 2 (AL2) vereist een tweede factor; NIST SP 800-63B §4.2 (AAL2); **OWASP ASVS 4.0 V2.8.1** (vereist TOTP of gelijkwaardige OTP-implementatie)
- **Why:** Admin console access must require MFA to prevent account takeover from credential theft alone. TOTP provides a second factor that is not transmitted over the network.
- **Implementation:** `keycloak.config.adminOtpEnabled: true` in `values.yaml` — sets `CONFIGURE_TOTP` as a default required action on the master realm via `keycloak-master-realm-config.yaml`

### admin-cli Flow Restriction

| Setting | Current value | Keycloak default | Status |
|---------|--------------|-----------------|--------|
| `standardFlowEnabled` | `false` | `true` | ✅ Configured (was true) |
| `implicitFlowEnabled` | `false` | `false` | ✅ Configured — restated explicitly |
| `directAccessGrantsEnabled` | `true` | `true` | ✅ Kept — required for bootstrap |

**`admin-cli` standardFlowEnabled / implicitFlowEnabled: false` ← changed from Keycloak defaults**
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.2** (Geprivilegieerde toegangsrechten); **OWASP ASVS 4.0 V2.1** — ongebruikte authenticatie-flows moeten worden uitgeschakeld
- **Why:** `admin-cli` ships with the Authorization Code and Implicit flows enabled by default, even though the only legitimate use in this chart is the one-time `podiumd-admin` bootstrap login via Direct Access Grants (ROPC) — see `templates/keycloak-ensure-operator-sa.yaml` — plus the `/kc-idp-secret` operator fallback. PKCE would **not** have protected this: it only hardens the Authorization Code flow, and nothing in this chart drives `admin-cli` through that flow. Disabling the unused browser-redirect flows instead closes the actual attack surface — a future stray redirect-URI addition can no longer turn this public client into an authorization-code-interception target.
- **Direct Access Grants deliberately kept enabled:** this is the legitimate, actively-used bootstrap mechanism (see `keycloak-ensure-operator-sa.yaml`) — the `podiumd-admin` account it authenticates is disabled again immediately after bootstrap completes, and all subsequent machine traffic switches to `client_credentials` with a dedicated `keycloak-operator` client.
- **History:** Flagged in the GreyBox Pentest Rotterdam (2026-06-11) as "Direct Access Grants toegestaan op public client" (tracked as [IN-2289](https://dimpact.atlassian.net/browse/IN-2289)). Direct Access Grants were kept as-is (they are the legitimate bootstrap path), and the browser-flow lockdown was added as a follow-up hardening step. **Solves [IN-2456](https://dimpact.atlassian.net/browse/IN-2456).**
- **Implementation:** `keycloak-master-realm-config.yaml` → `clients` → `admin-cli.standardFlowEnabled: false`, `implicitFlowEnabled: false`

### Audit Logging

| Setting | Current value | Keycloak default | Status |
|---------|--------------|-----------------|--------|
| `eventsEnabled` | `true` | `false` | ✅ Configured (was false) |
| `adminEventsEnabled` | `true` | `false` | ✅ Configured (was false) |
| `adminEventsDetailsEnabled` | `true` | `false` | ✅ Configured (was false) |
| `eventsExpiration` | `2592000` s (30 d) | not set | ✅ Configured (was not set) |

**`eventsEnabled: true` / `adminEventsEnabled: true` / `adminEventsDetailsEnabled: true`** ← changed from false
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.15** (Log-informatie — vastleggen, bewaren en beoordelen van logboeken); **NIS2 / Cbw** artikel 21(2)(h) (monitoring en logging als onderdeel van beveiligingsmaatregelen); **OWASP ASVS 4.0 V7.1.1** (alle authenticatiegebeurtenissen vastleggen); **NCSC Webapplicaties** — sectie Logging en monitoring
- **Why:** Without event logging, there is no audit trail for authentication events, failed login attempts, or administrative changes. BIO 2.0 §8.15 requires that security-relevant events are logged and retained. `adminEventsDetailsEnabled` captures the full request representation for admin events (who changed what).
- **Note:** Keycloak stores events in the application database. For long-term retention (BIO 2.0 requires ≥ 1 year for security logs), events should be shipped to a centralized log management system (e.g., Azure Monitor, Elasticsearch/OpenSearch). The in-DB retention of 30 days is a minimum buffer, not a substitute for SIEM integration.
- **Implementation:** `keycloak-master-realm-config.yaml` → `eventsEnabled`, `adminEventsEnabled`, `adminEventsDetailsEnabled`

**`eventsExpiration: 2592000`** ← changed from unset
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.15**; **OWASP ASVS 4.0 V7.2.2**
- **Why:** Without an expiration, Keycloak retains events indefinitely in the database, leading to unbounded table growth. 30 days provides a practical operational buffer. Long-term retention is the responsibility of the log shipping pipeline.
- **Implementation:** `keycloak-master-realm-config.yaml` → `eventsExpiration`

### Offline Session Max Lifespan

| Setting | Current value | Keycloak default | Status |
|---------|--------------|-----------------|--------|
| `offlineSessionMaxLifespanEnabled` | `true` | `false` | ✅ Configured (was false) |
| `offlineSessionMaxLifespan` | `7776000` s (90 d) | `5184000` s (60 d) | ✅ Configured |
| `offlineSessionIdleTimeout` | `2592000` s (30 d) | `2592000` s | ✅ Default |

**`offlineSessionMaxLifespanEnabled: true` / `offlineSessionMaxLifespan: 7776000`** ← changed from disabled
- **Standard:** **RFC 9700** (OAuth 2.0 Security BCP) §2.2.2 — refresh tokens must be bounded by maximum lifetime; **Forum / OAuth NL GOV**; BIO 2.0 / ISO 27002:2022 maatregel **8.5**; **OWASP ASVS 4.0 V3.3.4**
- **Why:** Without a maximum lifespan, offline sessions (used by native/mobile apps and persistent refresh tokens) never expire by absolute age — only by idle timeout. If a refresh token is stolen and used before the idle timeout resets, it can be kept alive indefinitely. Bounding lifetime to 90 days limits the maximum exposure window.
- **Implementation:** `keycloak-master-realm-config.yaml` → `offlineSessionMaxLifespanEnabled`, `offlineSessionMaxLifespan`

## Podiumd Realm

The podiumd realm exclusively serves beheer (management) users and municipality staff.
**Citizens do not authenticate directly in this realm** — they use centralized login methods (e.g. DigiD, eHerkenning, Microsoft Entra ID) configured per application. Settings are therefore calibrated for privileged internal users, not a general public audience.

### Browser Security Headers

| Setting | Value | Status |
|---------|-------|--------|
| `xContentTypeOptions` | `nosniff` | ✅ Configured |
| `xRobotsTag` | `none` | ✅ Configured |
| `xFrameOptions` | `SAMEORIGIN` | ✅ Configured |
| `contentSecurityPolicy` | `frame-src 'self'; frame-ancestors 'self'; object-src 'none';` | ✅ Configured |
| `xXSSProtection` | `1; mode=block` | ✅ Configured |
| `strictTransportSecurity` | `max-age=31536000; includeSubDomains` | ✅ Configured (was empty) |

**`strictTransportSecurity: max-age=31536000; includeSubDomains`** ← changed from empty
- **Standard:** **Forum / HTTPS+HSTS** — RFC 6797; wettelijk verplicht per 1 juli 2023 (Wet digitale overheid); NCSC Webapplicaties — sectie HTTPS/HSTS
- **Why:** Same rationale as master realm. The citizen-facing login URL must enforce HSTS as it handles authentication for government services.
- **Implementation:** `keycloak-podiumd-realm-config.yaml` → `browserSecurityHeaders.strictTransportSecurity`

### Brute Force Protection

| Setting | Current value | Keycloak default | Status |
|---------|--------------|-----------------|--------|
| `bruteForceProtected` | `true` | `false` | ✅ Configured (was false) |
| `failureFactor` | `5` | `30` | ✅ Configured (was 30) |
| `waitIncrementSeconds` | `60` | `60` | ✅ Default |
| `maxFailureWaitSeconds` | `900` | `900` | ✅ Default |
| `minimumQuickLoginWaitSeconds` | `60` | `60` | ✅ Default |

**`bruteForceProtected: true`** ← changed from false
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.5** (Authenticatie-informatie beveiligen); NCSC Webapplicaties — sectie Toegangsbeheer; NIST SP 800-63B §5.2.2
- **Why:** Without brute force protection, an attacker can attempt unlimited login attempts. Required for all authentication mechanisms under BIO 2.0.
- **Implementation:** `keycloak-podiumd-realm-config.yaml` → `bruteForceProtected`

**`failureFactor: 5`** ← changed from 30
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.5**; NIST SP 800-63B §5.2.2 — aanbevolen maximaal 5-10 pogingen voor account lockout
- **Why:** 30 failed attempts is far too permissive. 5 attempts allows for typos while still preventing automated attacks.
- **Implementation:** `keycloak-podiumd-realm-config.yaml` → `failureFactor`

### Password Policy

| Setting | Value | Status |
|---------|-------|--------|
| `passwordPolicy` | `length(12) and notUsername(undefined) and notEmail(undefined) and passwordHistory(5)` | ✅ Configured (was empty) |

**`passwordPolicy`** ← changed from empty
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **5.17** (Authenticatie-informatie); NIST SP 800-63B §5.1.1
- **Why:** Local back-office accounts need a password policy. Policy follows NIST SP 800-63B guidance: emphasize length over complexity, prevent credential stuffing by blocking username/email reuse, and reduce password reuse risk via history. Complexity rules (uppercase, special chars) are deliberately omitted per NIST SP 800-63B §5.1.1 which shows they encourage predictable substitutions without improving security.
  - `length(12)` — minimum 12 characters (exceeds NIST §5.1.1 minimum of 8; aligns with NCSC recommendations)
  - `notUsername` — cannot use the username as the password
  - `notEmail` — cannot use the email address as the password
  - `passwordHistory(5)` — prevents reuse of the last 5 passwords
- **Note:** Users authenticating via external IdPs (DigiD, Microsoft Entra ID) are not affected by this policy.
- **Implementation:** `keycloak-podiumd-realm-config.yaml` → `passwordPolicy: "length(12) and notUsername(undefined) and notEmail(undefined) and passwordHistory(5)"`

### Session Settings

| Setting | Current value | Keycloak default | Status |
|---------|--------------|-----------------|--------|
| `accessTokenLifespan` | `60` s | `300` s (5 min) | ✅ Configured (was 300) |
| `ssoSessionIdleTimeout` | `1800` s (30 min) | `1800` s | ✅ Default |
| `ssoSessionMaxLifespan` | `36000` s (10 h) | `36000` s | ✅ Default |
| `rememberMe` | `false` | `false` | ✅ Configured (was true) |

**`accessTokenLifespan: 60`** ← changed from 300
- **Standard:** **Forum / OAuth NL GOV** — vereist korte token levensduur; BIO 2.0 / ISO 27002:2022 maatregel **8.5**; NIST SP 800-63B §7.1
- **Why:** Access tokens should have a short lifespan to limit the damage if a token is stolen. The Keycloak default of 300 s (5 min) is too long. 60 s matches the master realm setting and is standard practice for OAuth2 flows used here.
- **Implementation:** `keycloak-podiumd-realm-config.yaml` → `accessTokenLifespan`

**`rememberMe: false`** ← changed from true
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.5**; NCSC Webapplicaties — sectie Sessiebeheer; OWASP ASVS 4.0 §3.3
- **Why:** The podiumd realm exclusively serves beheer and municipality staff — no citizens. Persistent sessions via "remember me" increase risk of unauthorized access from unattended or shared workstations, which is not acceptable for privileged internal users. There is no citizen UX argument to balance against the risk.
- **Implementation:** `keycloak-podiumd-realm-config.yaml` → `rememberMe: false`

### Refresh Token Rotation

| Setting | Current value | Keycloak default | Status |
|---------|--------------|-----------------|--------|
| `revokeRefreshToken` | `true` | `false` | ✅ Configured (was false) |
| `refreshTokenMaxReuse` | `0` | `0` | ✅ Default |

**`revokeRefreshToken: true`** ← changed from false
- **Standard:** **Forum / OAuth NL GOV** (Logius NL GOV Assurance Profile for OAuth 2.0); RFC 9700 (OAuth 2.0 Security BCP) §2.2.2
- **Why:** Same rationale as master realm — each refresh token may only be used once, enabling theft detection.
- **Implementation:** `keycloak-podiumd-realm-config.yaml` → `revokeRefreshToken`
- **Implementation:** `keycloak-master-realm-config.yaml` → `revokeRefreshToken: true`

### Token Signing Algorithm

| Setting | Current value | Keycloak default | Status |
|---------|--------------|-----------------|--------|
| `defaultSignatureAlgorithm` | `RS256` | `RS256` (implicit) | ✅ Configured — restated explicitly (was implicit) |

**`defaultSignatureAlgorithm: RS256`** ← explicitly pinned, no behavior change
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.24** (Gebruik van cryptografie); NIST SP 800-63B §7.1; **OWASP ASVS 4.0 V3.5.3** — tokens moeten met een asymmetrisch algoritme worden ondertekend
- **Why:** Keycloak generates both an `rsa-generated` (RS256) and an `hmac-generated` (HS512) key provider on every fresh realm by default, regardless of chart configuration — a pentest observed the active HS512 key and flagged it as symmetric-key signing risk. No client in this chart overrides its per-client signature algorithm (confirmed: no `signatureAlgorithm`/`defaultSignatureAlgorithm` reference anywhere else in `keycloak-podiumd-realm-config.yaml`), so tokens were already being signed with RS256 by Keycloak's own implicit default. Setting `defaultSignatureAlgorithm: RS256` explicitly removes the ambiguity and pins the choice in code rather than relying on Keycloak's default staying unchanged across versions.
- **Scope note:** this does **not** remove the HS512 key provider itself — Keycloak still generates and keeps it active on every realm. Removing it is a separate, more invasive change (realm `components` config) that risks rejecting the request if anything unexpectedly depends on that key, and needs its own verification before attempting — not bundled into this fix.
- **History:** Flagged in the GreyBox Pentest Rotterdam (2026-06-11) as "Gebruik van HS512 (symmetrische signing key) voor token signing" (DIV-2602-M-03, finding 17).
- **Implementation:** `keycloak-podiumd-realm-config.yaml` → `defaultSignatureAlgorithm: RS256`

### Login Settings

| Setting | Current value | Keycloak default | Status |
|---------|--------------|-----------------|--------|
| `registrationAllowed` | `false` | `false` | ✅ Configured (explicitly set) |
| `resetPasswordAllowed` | `false` | `false` | ✅ Default — password reset via email disabled |
| `rememberMe` | `false` | `false` | ✅ Configured (was true) — see Session Settings |
| `verifyEmail` | `false` | `false` | ✅ Default — not applicable |
| `loginWithEmailAllowed` | `true` | `true` | ✅ Default |
| `duplicateEmailsAllowed` | `false` | `false` | ✅ Default |
| `editUsernameAllowed` | `false` | `false` | ✅ Default |

**`registrationAllowed: false`** ← explicitly set
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.2** (Geprivilegieerde toegangsrechten) — toegang mag uitsluitend worden verleend door een beheerder, nooit door zelfregistratie.
- **Why:** All accounts are pre-provisioned by administrators. Self-registration has no legitimate use case in a realm serving only internal beheer and municipality staff.

**`rememberMe: false`** ← changed from true
- See Session Settings above for full rationale.

### Account Console (Self-Service Portal)

| Setting | Value | Keycloak default | Status |
|---|---|---|---|
| `account-console` client | `enabled: false` | enabled | ✅ Configured (was enabled) |
| `account` client | `enabled: false` | enabled | ✅ Configured (was enabled) |

**`account-console` and `account` clients disabled** ← explicitly set
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.2** (Geprivilegieerde toegangsrechten); **OWASP ASVS 4.0 V2.1** — account management must be administrator-controlled.
- **Why:** The Keycloak Account Console (`/realms/podiumd/account`) is a built-in self-service portal where authenticated users can update profile fields, change their password, manage TOTP devices, and revoke sessions. None of these actions are appropriate for self-service in a realm serving only admin-provisioned beheer staff. Disabling both clients removes the portal entirely.
- **Implementation:** `keycloak-podiumd-realm-config.yaml` → `clients` → `account-console.enabled: false`, `account.enabled: false`

### admin-cli Flow Restriction

| Setting | Current value | Keycloak default | Status |
|---------|--------------|-----------------|--------|
| `standardFlowEnabled` | `false` | `true` | ✅ Configured (was true) |
| `implicitFlowEnabled` | `false` | `false` | ✅ Configured — restated explicitly |
| `directAccessGrantsEnabled` | `true` | `true` | ✅ Kept — see note below |

**`admin-cli` standardFlowEnabled / implicitFlowEnabled: false` ← changed from Keycloak defaults**
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.2**; **OWASP ASVS 4.0 V2.1**
- **Why:** Same rationale as the master realm entry — `admin-cli` ships with the browser-redirect flows enabled by default. Unlike the master realm, **no bootstrap or ROPC flow relies on `admin-cli` in this realm at all**; it is disabled here purely as defense-in-depth so a future redirect-URI misconfiguration can't turn it into an exploitable public client. `directAccessGrantsEnabled` is left at the Keycloak default since nothing in this realm actively needs it disabled either way — the flows that matter (standard/implicit) are the ones closed off.
- **History:** Same pentest finding and Jira reference as the master realm entry — [IN-2289](https://dimpact.atlassian.net/browse/IN-2289) / **Solves [IN-2456](https://dimpact.atlassian.net/browse/IN-2456)**.
- **Implementation:** `keycloak-podiumd-realm-config.yaml` → `clients` → `admin-cli.standardFlowEnabled: false`, `implicitFlowEnabled: false`

### PABC Keycloak Admin REST API Client — Flow Restriction

| Setting | Current value | Keycloak default | Status |
|---------|--------------|-----------------|--------|
| `standardFlowEnabled` | `false` | `true` | ✅ Configured (was true) |
| `implicitFlowEnabled` | `false` | `false` | ✅ Configured — restated explicitly |
| `directAccessGrantsEnabled` | `false` | `true` | ✅ Configured (was true) |
| `serviceAccountsEnabled` | `true` | `false` | ✅ Unchanged — this is the client's sole purpose |
| `redirectUris` | (none) | (none) | ⚠️ Still unset — see note below |

**`pabc-keycloak-admin` flows restricted to service-account-only** ← changed from Keycloak defaults
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.2** (Geprivilegieerde toegangsrechten); **OWASP ASVS 4.0 V2.1** — ongebruikte authenticatie-flows moeten worden uitgeschakeld
- **Why:** This client (`.Values.pabc.settings.keycloakAdmin.clientId`) exists solely so PABC's own backend can call the Keycloak Admin REST API via its service account — it has never had a legitimate interactive use. Left at Keycloak's defaults it also carried `standardFlowEnabled: true` and `directAccessGrantsEnabled: true` with no `redirectUris` configured at all: an enabled-but-unusable authorization code flow (nowhere valid to redirect to) plus an unused password-grant path — both closed off now. No `redirectUris` are added since the client has no interactive flow left that would need one.
- **History:** Flagged in the GreyBox Pentest Rotterdam (2026-06-11) as two related findings on the same client: "Ontbrekende redirect URI configuratie" and "Serviceaccounts gecombineerd met extra flows" (DIV-2602-M-03, findings 6 and 15). Both addressed by this single change.
- **Implementation:** `keycloak-podiumd-realm-config.yaml` → `clients` → `<pabc.settings.keycloakAdmin.clientId>.standardFlowEnabled/implicitFlowEnabled/directAccessGrantsEnabled: false`

### samaccountname User Profile Restriction

| Setting | Current value | Keycloak default | Status |
|---------|--------------|-----------------|--------|
| `attributes.userProfileEnabled` | `"true"` | not set | ✅ Configured (was not set) |
| `userProfile.unmanagedAttributePolicy` | `ENABLED` | (unset — equivalent behavior) | ✅ Configured — restated explicitly |
| `userProfile.attributes[username/email/firstName/lastName]` | admin+user view/edit | admin+user view/edit | ✅ Re-declared verbatim — unchanged, see note below |
| `userProfile.attributes[samaccountname].permissions.edit` | `admin` only | (not previously declared — implicitly admin+user) | ✅ Configured (was editable by user) |

**`samaccountname` locked to admin-only edit** ← changed from implicitly user-editable
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.2** (Geprivilegieerde toegangsrechten) — gebruikersattributen die voor identificatie/autorisatie worden gebruikt mogen niet door de gebruiker zelf wijzigbaar zijn; **OWASP ASVS 4.0 V2.1**
- **Why:** `samaccountname` is a genuine stored Keycloak user attribute (not a live pass-through of an upstream IdP claim) — confirmed via the `oidc-usermodel-attribute-mapper` protocol mappers on both the `ita` and `kiss` clients (`user.attribute: samaccountname`), which read this same stored value into their tokens. Left ungoverned, Keycloak's default behavior lets the user edit any attribute not declared in the realm's User Profile config, including this one — and since it's used for identification/authorization in downstream systems (ITA, KISS), a self-editable value here is a real impersonation/privilege-escalation risk.
- **Note on scope:** Keycloak's User Profile update API rejects a partial attribute list — it treats `username`/`email`'s absence as an attempt to delete them, and returns HTTP 400 (confirmed live: `"The attribute 'username' can not be removed, The attribute 'email' can not be removed"`). `username`, `email`, `firstName` and `lastName` are therefore re-declared verbatim, matching Keycloak 26's own out-of-the-box defaults exactly (confirmed via `GET /admin/realms/podiumd/users/profile` against a fresh realm) — their behavior is unchanged. `unmanagedAttributePolicy: ENABLED` keeps every other, undeclared attribute exactly as editable as before this block existed. Only `samaccountname`'s edit permission actually changes.
- **Open question — not resolvable from this repo:** whether this restriction meaningfully reduces real-world risk depends on how each gemeente's own Entra ID identity provider mapper populates `samaccountname` in the first place. Identity providers are deliberately not chart-managed (see `keycloak.config.realmIdentityProviders` — left empty by default so as not to overwrite gemeente-specific Entra configuration), so that mapper's sync mode lives entirely outside this chart. If it syncs on every login (`FORCE`), a user's self-edit would already have been silently reverted at next login regardless of this fix. If it only imports once (`IMPORT`), this fix is the only thing preventing permanent drift. This can only be checked against a specific gemeente's live IdP mapper configuration, not from chart code.
- **History:** Flagged in the GreyBox Pentest Rotterdam (2026-06-11) as "Onveilige inzet van user attributes zonder User Profiles" (DIV-2602-M-03, finding 5).
- **Implementation:** `keycloak-podiumd-realm-config.yaml` → `attributes.userProfileEnabled`, `userProfile`

### Audit Logging

| Setting | Current value | Keycloak default | Status |
|---------|--------------|-----------------|--------|
| `eventsEnabled` | `true` | `false` | ✅ Configured (was false) |
| `adminEventsEnabled` | `true` | `false` | ✅ Configured (was false) |
| `adminEventsDetailsEnabled` | `true` | `false` | ✅ Configured (was false) |
| `eventsExpiration` | `2592000` s (30 d) | `10800` s | ✅ Configured (was 10800) |
| `adminEventsExpiration` (attribute) | `2592000` s (30 d) | `10800` s | ✅ Configured (was 10800) |

**`eventsEnabled: true` / `adminEventsEnabled: true` / `adminEventsDetailsEnabled: true`** — no change needed (already enabled on cluster); documented here for audit completeness
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.15**; **NIS2 / Cbw** artikel 21(2)(h); **OWASP ASVS 4.0 V7.1.1**; **NCSC Webapplicaties** — sectie Logging en monitoring
- **Note:** Same SIEM integration requirement applies as for master realm — in-DB retention of 30 days is a minimum operational buffer.
- **Implementation:** `keycloak-podiumd-realm-config.yaml` → `eventsEnabled`, `adminEventsEnabled`, `adminEventsDetailsEnabled`

**`eventsExpiration: 2592000` / `adminEventsExpiration: 2592000`** ← changed from 10800 (3 h)
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.15**; **OWASP ASVS 4.0 V7.2.2**
- **Why:** The previous value of 10800 s (3 hours) was far too short for any operational or forensic use. 30 days is the minimum practical buffer before events are expected to be in the SIEM.
- **Implementation:** `keycloak-podiumd-realm-config.yaml` → `eventsExpiration`, `attributes.adminEventsExpiration`

### PKCE Enforcement

| Setting | Value | Status |
|---------|-------|--------|
| `pkceCodeChallengeMethod` per client | `S256` | ⚙️ Available via `pkceEnabled` switch — disabled by default |

**`pkceCodeChallengeMethod: S256`** — available per client, disabled by default
- **Standard:** **RFC 9700** (OAuth 2.0 Security BCP) §2.1.1 — PKCE verplicht voor alle clients die authorization code flow gebruiken, ook voor confidential clients; **OWASP ASVS 4.0 V2.10.3**; **Forum / OAuth NL GOV**
- **Why:** Without PKCE, an attacker who intercepts the authorization code can exchange it for tokens without the client secret. PKCE binds the authorization code to the device that initiated the flow via a cryptographic challenge/verifier pair. S256 (SHA-256 hash of the verifier) is required — plain method is insecure.
- **History:** PKCE enforcement was deployed on 2026-03-16 and immediately caused HTTP 403 errors on all login pages. The PodiumD applications use `mozilla_django_oidc` which only added PKCE support in v4.0.0 (2024). PKCE enforcement was reverted until all components support and are configured to use PKCE.
- **Current implementation:** Each Keycloak client now has an individual `pkceEnabled` switch in `values.yaml` (default: `false`). Setting it to `true` adds `pkceCodeChallengeMethod: S256` to the client in the realm ConfigMap.
- **Enabling PKCE per component requires two aligned steps:**
  1. Set `<component>.configuration.pkceEnabled: true` (or `<component>.settings.oidc.pkceEnabled: true` for KISS/PABC/ZAC/ITA) in your env values file — this configures the Keycloak client.
  2. For Django apps: add `oidc_use_pkce: true` to the `oidc_db_config_admin_auth.items` entry in `configuration.data` — this tells the application to send `code_challenge` with each authorization request. Requires `mozilla_django_oidc >= 4.0.0`. Note: the upstream Maykin Media Helm charts (openzaak, openklant, openformulieren, openinwoner, opennotificaties, objecten [merged with the former objecttypen]) do **not** expose `oidc_use_pkce` as a chart value — `configuration.data` is the correct and only mechanism.
- **openarchiefbeheer exception:** openarchiefbeheer v1.1.1 does not yet support OIDC; the `pkceEnabled` switch is reserved for future use once OIDC is added.
- **ZAC exception:** ZAC does not currently support PKCE; the `pkceEnabled` switch is reserved for future use.
- **Non-Django apps (KISS, ITA, PABC):** These are frontend/ASP.NET Core apps. Their upstream charts do **not** expose an app-side PKCE toggle — there is no equivalent of `oidc_use_pkce`. Whether PKCE works transparently depends entirely on the OIDC client library version used by the application:
  - KISS and ITA are JS/Vue frontends — if they use a modern library (`oidc-client-ts` v2+), PKCE is typically used by default for auth code flow and enabling it on the Keycloak client side should be safe.
  - PABC is an ASP.NET Core app — PKCE in .NET's OpenIdConnect middleware is not configurable via the current `Oidc__*` env vars; enabling `pkceEnabled` on the Keycloak client should only be done after confirming the application's middleware configuration.
- **Action required:** For Django apps: verify each component has `mozilla_django_oidc >= 4.0.0` installed, then enable PKCE per component in env values once confirmed. For KISS/ITA/PABC: verify OIDC library PKCE compatibility before enabling.
- **Note on redirect URI wildcards:** All clients currently use path-wildcard redirect URIs (`https://app.example.nl/*`). RFC 9700 §4.1.3 recommends exact URI matching. This is accepted because all ingress terminates within the cluster and the NGINX ingress controller is managed and audited separately. Exact URIs will be evaluated per component when application callback paths are stable.

### Offline Session Max Lifespan

| Setting | Current value | Keycloak default | Status |
|---------|--------------|-----------------|--------|
| `offlineSessionMaxLifespanEnabled` | `true` | `false` | ✅ Configured (was false) |
| `offlineSessionMaxLifespan` | `7776000` s (90 d) | `5184000` s (60 d) | ✅ Configured |
| `offlineSessionIdleTimeout` | `2592000` s (30 d) | `2592000` s | ✅ Default |

**`offlineSessionMaxLifespanEnabled: true` / `offlineSessionMaxLifespan: 7776000`** ← changed from disabled
- **Standard:** **RFC 9700** §2.2.2; **Forum / OAuth NL GOV**; BIO 2.0 / ISO 27002:2022 maatregel **8.5**; **OWASP ASVS 4.0 V3.3.4**
- **Why:** Same rationale as master realm. 90-day maximum lifespan is a reasonable absolute bound on offline sessions for internal users.
- **Implementation:** `keycloak-podiumd-realm-config.yaml` → `offlineSessionMaxLifespanEnabled`, `offlineSessionMaxLifespan`

### OTP Algorithm (Under Investigation)

| Setting | Current value | Keycloak default | Status |
|---------|--------------|-----------------|--------|
| `otpPolicyAlgorithm` | `HmacSHA1` | `HmacSHA1` | ⚠️ Under investigation |
| `otpPolicyDigits` | `6` | `6` | ✅ Default |
| `otpPolicyPeriod` | `30` s | `30` s | ✅ Default |

**`otpPolicyAlgorithm: HmacSHA1`** — under investigation, no change yet
- **Standard:** NIST SP 800-63B §5.1.3.2 — TOTP (RFC 6238) using HMAC-SHA-1 is currently allowed but NIST notes SHA-256/512 as preferred; **FIPS 140-3** — HMAC-SHA-1 remains approved for TOTP specifically (distinct from general SHA-1 deprecation for digital signatures)
- **Why:** Upgrading from HmacSHA1 to HmacSHA256 would break all existing registered OTP devices (Google Authenticator, Microsoft Authenticator, etc.) and require all back-office users to re-enroll. The security improvement is marginal for TOTP — SHA-1 weaknesses (collision attacks) do not affect HMAC-SHA-1 in the TOTP context. Investigation is ongoing to determine whether re-enrollment impact is justified.
- **Action:** Evaluate per-organisation impact before implementing. If upgraded, coordinate with helpdesk for re-enrollment comms.
