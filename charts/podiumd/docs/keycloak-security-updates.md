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

---

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

**`strictTransportSecurity: max-age=31536000; includeSubDomains`** ← *changed from empty*
- **Standard:** **Forum / HTTPS+HSTS** — RFC 6797; wettelijk verplicht per 1 juli 2023 (Wet digitale overheid); NCSC Webapplicaties — sectie HTTPS/HSTS
- **Why:** Without HSTS, browsers may downgrade to HTTP after the first visit. Keycloak sets this header on all its responses; an empty value means no HSTS is sent even though TLS is used at the ingress.
- **Implementation:** `keycloak-master-realm-config.yaml` → `browserSecurityHeaders.strictTransportSecurity`

---

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

**`bruteForceProtected: true`** ← *changed from false*
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.5** (Beveiligde authenticatie); NCSC Webapplicaties — sectie Authenticatie (begrens inlogpogingen); NIST SP 800-63B §5.2.2; **OWASP ASVS 4.0 V2.2.1** (vereist rate-limiting of lockout na herhaalde mislukte pogingen)
- **Why:** Without brute force protection there is no lockout on failed login attempts. An attacker can make unlimited password guesses against the admin console.
- **Implementation:** `keycloak-master-realm-config.yaml` → `bruteForceProtected: true`

**`failureFactor: 5`** ← *changed from 30*
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.5**; NIST SP 800-63B §5.2.2 (recommends throttling after a small number of consecutive failures); NCSC Webapplicaties — sectie Authenticatie; **OWASP ASVS 4.0 V2.2.1**
- **Why:** 30 failed attempts is far too permissive. 5 consecutive failures is the widely accepted threshold before a temporary lockout is imposed.
- **Implementation:** `keycloak-master-realm-config.yaml` → `failureFactor: 5`

---

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

---

### Refresh Token Rotation

| Setting | Current value | Keycloak default | Status |
|---------|--------------|-----------------|--------|
| `revokeRefreshToken` | `true` | `false` | ✅ Configured (was false) |
| `refreshTokenMaxReuse` | `0` | `0` | ✅ Default |

**`revokeRefreshToken: true`** ← *changed from false*
- **Standard:** **Forum / OAuth NL GOV** (Logius NL GOV Assurance Profile for OAuth 2.0) — vereist gebruik van refresh token rotation om hergebruik te detecteren; RFC 9700 (OAuth 2.0 Security BCP) §2.2.2
- **Why:** Each refresh token may only be used once. If a stolen refresh token is replayed after the legitimate client already used it, Keycloak detects the duplicate use and revokes the entire session — providing theft detection.

---

### OTP / MFA

| Setting | Value | Status |
|---------|-------|--------|
| `adminOtpEnabled` (chart value) | `true` | ✅ Configured — TOTP `CONFIGURE_TOTP` set as default required action |

**OTP enforcement via `CONFIGURE_TOTP` required action**
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.5** (Beveiligde authenticatie) — vereist MFA voor beheerderstoegang; **Forum / OpenID NLGov** — authenticatiebetrouwbaarheidsniveau 2 (AL2) vereist een tweede factor; NIST SP 800-63B §4.2 (AAL2); **OWASP ASVS 4.0 V2.8.1** (vereist TOTP of gelijkwaardige OTP-implementatie)
- **Why:** Admin console access must require MFA to prevent account takeover from credential theft alone. TOTP provides a second factor that is not transmitted over the network.
- **Implementation:** `keycloak.config.adminOtpEnabled: true` in `values.yaml` — sets `CONFIGURE_TOTP` as a default required action on the master realm via `keycloak-master-realm-config.yaml`

---

### Audit Logging

| Setting | Current value | Keycloak default | Status |
|---------|--------------|-----------------|--------|
| `eventsEnabled` | `true` | `false` | ✅ Configured (was false) |
| `adminEventsEnabled` | `true` | `false` | ✅ Configured (was false) |
| `adminEventsDetailsEnabled` | `true` | `false` | ✅ Configured (was false) |
| `eventsExpiration` | `2592000` s (30 d) | not set | ✅ Configured (was not set) |

**`eventsEnabled: true` / `adminEventsEnabled: true` / `adminEventsDetailsEnabled: true`** ← *changed from false*
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.15** (Log-informatie — vastleggen, bewaren en beoordelen van logboeken); **NIS2 / Cbw** artikel 21(2)(h) (monitoring en logging als onderdeel van beveiligingsmaatregelen); **OWASP ASVS 4.0 V7.1.1** (alle authenticatiegebeurtenissen vastleggen); **NCSC Webapplicaties** — sectie Logging en monitoring
- **Why:** Without event logging, there is no audit trail for authentication events, failed login attempts, or administrative changes. BIO 2.0 §8.15 requires that security-relevant events are logged and retained. `adminEventsDetailsEnabled` captures the full request representation for admin events (who changed what).
- **Note:** Keycloak stores events in the application database. For long-term retention (BIO 2.0 requires ≥ 1 year for security logs), events should be shipped to a centralized log management system (e.g., Azure Monitor, Elasticsearch/OpenSearch). The in-DB retention of 30 days is a minimum buffer, not a substitute for SIEM integration.
- **Implementation:** `keycloak-master-realm-config.yaml` → `eventsEnabled`, `adminEventsEnabled`, `adminEventsDetailsEnabled`

**`eventsExpiration: 2592000`** ← *changed from unset*
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.15**; **OWASP ASVS 4.0 V7.2.2**
- **Why:** Without an expiration, Keycloak retains events indefinitely in the database, leading to unbounded table growth. 30 days provides a practical operational buffer. Long-term retention is the responsibility of the log shipping pipeline.
- **Implementation:** `keycloak-master-realm-config.yaml` → `eventsExpiration`

---

### Offline Session Max Lifespan

| Setting | Current value | Keycloak default | Status |
|---------|--------------|-----------------|--------|
| `offlineSessionMaxLifespanEnabled` | `true` | `false` | ✅ Configured (was false) |
| `offlineSessionMaxLifespan` | `7776000` s (90 d) | `5184000` s (60 d) | ✅ Configured |
| `offlineSessionIdleTimeout` | `2592000` s (30 d) | `2592000` s | ✅ Default |

**`offlineSessionMaxLifespanEnabled: true` / `offlineSessionMaxLifespan: 7776000`** ← *changed from disabled*
- **Standard:** **RFC 9700** (OAuth 2.0 Security BCP) §2.2.2 — refresh tokens must be bounded by maximum lifetime; **Forum / OAuth NL GOV**; BIO 2.0 / ISO 27002:2022 maatregel **8.5**; **OWASP ASVS 4.0 V3.3.4**
- **Why:** Without a maximum lifespan, offline sessions (used by native/mobile apps and persistent refresh tokens) never expire by absolute age — only by idle timeout. If a refresh token is stolen and used before the idle timeout resets, it can be kept alive indefinitely. Bounding lifetime to 90 days limits the maximum exposure window.
- **Implementation:** `keycloak-master-realm-config.yaml` → `offlineSessionMaxLifespanEnabled`, `offlineSessionMaxLifespan`

## Podiumd Realm

The podiumd realm is the end-user facing realm. It federates identities from external IdPs (DigiD, Microsoft Entra ID, eHerkenning). Local accounts exist for back-office users. All settings apply on top of the same Keycloak version and infrastructure as the master realm.

### Browser Security Headers

| Setting | Value | Status |
|---------|-------|--------|
| `xContentTypeOptions` | `nosniff` | ✅ Configured |
| `xRobotsTag` | `none` | ✅ Configured |
| `xFrameOptions` | `SAMEORIGIN` | ✅ Configured |
| `contentSecurityPolicy` | `frame-src 'self'; frame-ancestors 'self'; object-src 'none';` | ✅ Configured |
| `xXSSProtection` | `1; mode=block` | ✅ Configured |
| `strictTransportSecurity` | `max-age=31536000; includeSubDomains` | ✅ Configured (was empty) |

**`strictTransportSecurity: max-age=31536000; includeSubDomains`** ← *changed from empty*
- **Standard:** **Forum / HTTPS+HSTS** — RFC 6797; wettelijk verplicht per 1 juli 2023 (Wet digitale overheid); NCSC Webapplicaties — sectie HTTPS/HSTS
- **Why:** Same rationale as master realm. The citizen-facing login URL must enforce HSTS as it handles authentication for government services.
- **Implementation:** `keycloak-podiumd-realm-config.yaml` → `browserSecurityHeaders.strictTransportSecurity`

---

### Brute Force Protection

| Setting | Current value | Keycloak default | Status |
|---------|--------------|-----------------|--------|
| `bruteForceProtected` | `true` | `false` | ✅ Configured (was false) |
| `failureFactor` | `5` | `30` | ✅ Configured (was 30) |
| `waitIncrementSeconds` | `60` | `60` | ✅ Default |
| `maxFailureWaitSeconds` | `900` | `900` | ✅ Default |
| `minimumQuickLoginWaitSeconds` | `60` | `60` | ✅ Default |

**`bruteForceProtected: true`** ← *changed from false*
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.5** (Authenticatie-informatie beveiligen); NCSC Webapplicaties — sectie Toegangsbeheer; NIST SP 800-63B §5.2.2
- **Why:** Without brute force protection, an attacker can attempt unlimited login attempts. Required for all authentication mechanisms under BIO 2.0.
- **Implementation:** `keycloak-podiumd-realm-config.yaml` → `bruteForceProtected`

**`failureFactor: 5`** ← *changed from 30*
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.5**; NIST SP 800-63B §5.2.2 — aanbevolen maximaal 5-10 pogingen voor account lockout
- **Why:** 30 failed attempts is far too permissive. 5 attempts allows for typos while still preventing automated attacks.
- **Implementation:** `keycloak-podiumd-realm-config.yaml` → `failureFactor`

---

### Password Policy

| Setting | Value | Status |
|---------|-------|--------|
| `passwordPolicy` | `length(12) notUsername notEmail passwordHistory(5)` | ✅ Configured (was empty) |

**`passwordPolicy`** ← *changed from empty*
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **5.17** (Authenticatie-informatie); NIST SP 800-63B §5.1.1
- **Why:** Local back-office accounts need a password policy. Policy follows NIST SP 800-63B guidance: emphasize length over complexity, prevent credential stuffing by blocking username/email reuse, and reduce password reuse risk via history. Complexity rules (uppercase, special chars) are deliberately omitted per NIST SP 800-63B §5.1.1 which shows they encourage predictable substitutions without improving security.
  - `length(12)` — minimum 12 characters (exceeds NIST §5.1.1 minimum of 8; aligns with NCSC recommendations)
  - `notUsername` — cannot use the username as the password
  - `notEmail` — cannot use the email address as the password
  - `passwordHistory(5)` — prevents reuse of the last 5 passwords
- **Note:** Users authenticating via external IdPs (DigiD, Microsoft Entra ID) are not affected by this policy.
- **Implementation:** `keycloak-podiumd-realm-config.yaml` → `passwordPolicy`

---

### Session Settings

| Setting | Current value | Keycloak default | Status |
|---------|--------------|-----------------|--------|
| `accessTokenLifespan` | `60` s | `300` s (5 min) | ✅ Configured (was 300) |
| `ssoSessionIdleTimeout` | `1800` s (30 min) | `1800` s | ✅ Default |
| `ssoSessionMaxLifespan` | `36000` s (10 h) | `36000` s | ✅ Default |
| `rememberMe` | `true` | `false` | ⚠️ Accepted risk (intentional) |

**`accessTokenLifespan: 60`** ← *changed from 300*
- **Standard:** **Forum / OAuth NL GOV** — vereist korte token levensduur; BIO 2.0 / ISO 27002:2022 maatregel **8.5**; NIST SP 800-63B §7.1
- **Why:** Access tokens should have a short lifespan to limit the damage if a token is stolen. The Keycloak default of 300 s (5 min) is too long. 60 s matches the master realm setting and is standard practice for OAuth2 flows used here.
- **Implementation:** `keycloak-podiumd-realm-config.yaml` → `accessTokenLifespan`

**`rememberMe: true`** — accepted risk, no change
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.5**; NCSC Webapplicaties — sectie Sessiebeheer
- **Why:** "Remember me" allows persistent sessions across browser restarts (stores a long-lived session cookie). For a citizen-facing portal this is intentionally enabled to improve UX — citizens should not be forced to re-authenticate every browser session. This is an accepted risk documented here.
- **Mitigating controls:** Brute force protection, short access token lifespan, refresh token rotation, and HSTS are all in place.
- **Implementation:** No change — `rememberMe: true` is explicitly set in `keycloak-podiumd-realm-config.yaml`.

---

### Refresh Token Rotation

| Setting | Current value | Keycloak default | Status |
|---------|--------------|-----------------|--------|
| `revokeRefreshToken` | `true` | `false` | ✅ Configured (was false) |
| `refreshTokenMaxReuse` | `0` | `0` | ✅ Default |

**`revokeRefreshToken: true`** ← *changed from false*
- **Standard:** **Forum / OAuth NL GOV** (Logius NL GOV Assurance Profile for OAuth 2.0); RFC 9700 (OAuth 2.0 Security BCP) §2.2.2
- **Why:** Same rationale as master realm — each refresh token may only be used once, enabling theft detection.
- **Implementation:** `keycloak-podiumd-realm-config.yaml` → `revokeRefreshToken`
- **Implementation:** `keycloak-master-realm-config.yaml` → `revokeRefreshToken: true`

---

### Login Settings

| Setting | Current value | Keycloak default | Status |
|---------|--------------|-----------------|--------|
| `registrationAllowed` | `false` | `false` | ✅ Default — self-registration must be disabled on admin realm |
| `resetPasswordAllowed` | `false` | `false` | ✅ Default — password reset via email disabled on admin realm |
| `rememberMe` | `false` | `false` | ✅ Default — persistent sessions undesirable for admin realm |
| `verifyEmail` | `false` | `false` | ✅ Default — not applicable for admin realm |
| `loginWithEmailAllowed` | `true` | `true` | ✅ Default |
| `duplicateEmailsAllowed` | `false` | `false` | ✅ Default |
| `editUsernameAllowed` | `false` | `false` | ✅ Default |

**`registrationAllowed: false`**
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.2** (Geprivilegieerde toegangsrechten) — toegang tot beheerfuncties mag uitsluitend worden verleend door een beheerder, nooit door zelfregistratie.

**`rememberMe: false`**
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.5**; NCSC Webapplicaties — sectie Sessiebeheer
- **Why:** "Remember me" creates persistent browser sessions that survive browser restarts, increasing risk from unattended or shared workstations.

---

---

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

**`eventsExpiration: 2592000` / `adminEventsExpiration: 2592000`** ← *changed from 10800 (3 h)*
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.15**; **OWASP ASVS 4.0 V7.2.2**
- **Why:** The previous value of 10800 s (3 hours) was far too short for any operational or forensic use. 30 days is the minimum practical buffer before events are expected to be in the SIEM.
- **Implementation:** `keycloak-podiumd-realm-config.yaml` → `eventsExpiration`, `attributes.adminEventsExpiration`

---

### PKCE Enforcement

| Setting | Value | Status |
|---------|-------|--------|
| `pkce.code.challenge.method` | `S256` | ✅ Configured on all 15 clients (was not set) |

**`pkce.code.challenge.method: S256`** ← *changed from not set* — applied to all 15 explicitly defined clients
- **Standard:** **RFC 9700** (OAuth 2.0 Security BCP) §2.1.1 — PKCE verplicht voor alle clients die authorization code flow gebruiken, ook voor confidential clients; **OWASP ASVS 4.0 V2.10.3**; **Forum / OAuth NL GOV**
- **Why:** Without PKCE, an attacker who intercepts the authorization code (e.g., via a misconfigured redirect, browser history, or referrer header) can exchange it for tokens without having the client secret. PKCE binds the authorization code to the device that initiated the flow via a cryptographic challenge/verifier pair. S256 (SHA-256 hash of the verifier) is required — plain method is insecure.
- **Clients:** openzaak, abc, monitoring, opennotificaties, objecten, objecttypen, openklant, openformulieren, openinwoner, kiss, zac, zac-admin-client, ita, pabc, pabc-keycloak-admin
- **Note on redirect URI wildcards:** All clients currently use path-wildcard redirect URIs (`https://app.example.nl/*`). RFC 9700 §4.1.3 recommends exact URI matching. This is accepted because all ingress terminates within the cluster and the NGINX ingress controller is managed and audited separately — the attack surface for redirect URI manipulation is confined to the cluster network boundary. Exact URIs will be evaluated per component when application callback paths are stable.
- **Implementation:** `keycloak-podiumd-realm-config.yaml` → `clients[*].attributes.pkce.code.challenge.method`

---

### Offline Session Max Lifespan

| Setting | Current value | Keycloak default | Status |
|---------|--------------|-----------------|--------|
| `offlineSessionMaxLifespanEnabled` | `true` | `false` | ✅ Configured (was false) |
| `offlineSessionMaxLifespan` | `7776000` s (90 d) | `5184000` s (60 d) | ✅ Configured |
| `offlineSessionIdleTimeout` | `2592000` s (30 d) | `2592000` s | ✅ Default |

**`offlineSessionMaxLifespanEnabled: true` / `offlineSessionMaxLifespan: 7776000`** ← *changed from disabled*
- **Standard:** **RFC 9700** §2.2.2; **Forum / OAuth NL GOV**; BIO 2.0 / ISO 27002:2022 maatregel **8.5**; **OWASP ASVS 4.0 V3.3.4**
- **Why:** Same rationale as master realm. 90-day maximum lifespan for citizen-facing persistent sessions (enabled by `rememberMe: true`) is a reasonable bound that balances UX with security.
- **Implementation:** `keycloak-podiumd-realm-config.yaml` → `offlineSessionMaxLifespanEnabled`, `offlineSessionMaxLifespan`

---

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
