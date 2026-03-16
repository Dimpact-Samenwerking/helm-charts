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
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.5** (Beveiligde authenticatie); NCSC Webapplicaties — sectie Authenticatie (begrens inlogpogingen); NIST SP 800-63B §5.2.2
- **Why:** Without brute force protection there is no lockout on failed login attempts. An attacker can make unlimited password guesses against the admin console.
- **Implementation:** `keycloak-master-realm-config.yaml` → `bruteForceProtected: true`

**`failureFactor: 5`** ← *changed from 30*
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.5**; NIST SP 800-63B §5.2.2 (recommends throttling after a small number of consecutive failures); NCSC Webapplicaties — sectie Authenticatie
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

### OTP / MFA

| Setting | Value | Status |
|---------|-------|--------|
| `adminOtpEnabled` (chart value) | `true` | ✅ Configured — TOTP `CONFIGURE_TOTP` set as default required action |

**OTP enforcement via `CONFIGURE_TOTP` required action**
- **Standard:** BIO 2.0 / ISO 27002:2022 maatregel **8.5** (Beveiligde authenticatie) — vereist MFA voor beheerderstoegang; **Forum / OpenID NLGov** — authenticatiebetrouwbaarheidsniveau 2 (AL2) vereist een tweede factor; NIST SP 800-63B §4.2 (AAL2)
- **Why:** Admin console access must require MFA to prevent account takeover from credential theft alone. TOTP provides a second factor that is not transmitted over the network.
- **Implementation:** `keycloak.config.adminOtpEnabled: true` in `values.yaml` — sets `CONFIGURE_TOTP` as a default required action on the master realm via `keycloak-master-realm-config.yaml`
