# Security Review — podiumd chart

> Reviewed: 2026-04-07

## Summary

The podiumd chart is a well-structured umbrella chart for a Dutch municipal services platform. The Keycloak CR, Redis HA, and observability components show good security hygiene (runAsNonRoot, capabilities dropped, seccompProfile, brute-force protection, HSTS). However, several systemic gaps exist across custom templates: **all custom Deployments and Jobs lack container-level security contexts**, **multiple sensitive values (OIDC secrets, API tokens, JWT signing secrets) are stored in ConfigMaps rather than Secrets**, and **every chart has ships with hardcoded placeholder credentials** that Helm does not prevent from being deployed unchanged. There are also no NetworkPolicies and the API proxy disables upstream TLS verification by default.

---

## Findings

### 1. Secret Management — Credentials in ConfigMaps

- [ ] **[High]** The ZGW JWT signing secret (`openzaak.create_required_catalogi_job.secret`) is stored in a ConfigMap (`create-required-catalogi-configmap`) rather than a Kubernetes Secret, making it readable by any ServiceAccount with ConfigMap read access in the namespace. _File: `templates/create-required-catalogi.yaml`, line 13._ Remediation: Move `SECRET` to a separate Secret and reference it via `secretRef` in the Job.

- [ ] **[High]** The Objecttypen API token (`objecttypen.configuration.token`) is stored in a ConfigMap (`create-required-objecttypen-configmap`) rather than a Kubernetes Secret. _File: `templates/create-required-objecttypen.yaml`, line 11._ Remediation: Move `AUTHORIZATION_TOKEN` to a Secret and reference it via `secretKeyRef`.

- [ ] **[High]** All Keycloak OIDC client secrets (`openzaak.configuration.oidcSecret`, `opennotificaties.configuration.oidcSecret`, `objecten.configuration.oidcSecret`, `objecttypen.configuration.oidcSecret`, `openklant.configuration.oidcSecret`, `openformulieren.configuration.oidcSecret`, `openinwoner.configuration.oidcSecret`, `kiss.settings.oidc.clientSecret`, `keycloak.config.clients.monitoring.secret`) are rendered as plaintext into a ConfigMap (`keycloak-podiumd-realm-config`) that is accessible to any workload with ConfigMap read access. _File: `templates/keycloak-podiumd-realm-config.yaml`._ Remediation: Use keycloak-config-cli's `SECRET_` env-var substitution pattern to pull secrets from Kubernetes Secrets at import time instead of embedding them in the ConfigMap.

---

### 2. Hardcoded Default Credentials

- [ ] **[High]** `keycloak-operator.jobs.ensureOperatorSa.clientSecret: "changeme"` — the Keycloak operator client secret has a well-known default. If deployed without override, any actor that can reach Keycloak's internal endpoint can authenticate as the operator service account (which holds master-realm admin role). _File: `values.yaml`, line 66._ Remediation: Remove the default or add a `required` validation annotation; document that this must be set before first deploy.

- [ ] **[High]** `keycloak.auth.adminPassword: "changemenow"` — bootstrap Keycloak admin password shipped as a well-known default. _File: `values.yaml`, line 100._ Remediation: Remove the default value; add a chart validation check (`fail` in `_helpers.tpl`) that aborts if it is still `"changemenow"`.

- [ ] **[Medium]** Multiple ZAC secrets have well-known placeholder defaults that are not placeholders (they look like real short secrets): `zac.auth.secret: changeme` (line 2378), `zac.db.password: changeme` (line 2400), `zac.keycloak.adminClient.secret: changeme` (line 2427), `zac.notificationsSecretKey: "changeme"` (line 2452), `zac.zgwApis.secret: changeme` (line 2569). _File: `values.yaml`._ Remediation: Replace with clearly non-functional placeholders (e.g. `"REPLACE_ME"`) and add `required` validation guards in the sub-chart or a wrapper `_helpers.tpl` check.

- [ ] **[Medium]** `keycloak.config.clients.monitoring.secret: "monitoring_secret"` is a predictable default for the Grafana/monitoring OIDC client. _File: `values.yaml`, line 153._ Remediation: Replace with empty default and require explicit configuration.

- [ ] **[Medium]** `openarchiefbeheer.configuration.oidcSecret: "abc"` is an extremely weak placeholder that would be live if `openarchiefbeheer.enabled` is toggled to `true` without overriding the secret. _File: `values.yaml`, line 1118._ Remediation: Replace with an empty string default and add a validation guard guarded by `openarchiefbeheer.enabled`.

- [ ] **[Medium]** `zac.klantinteractiesApi.token: openklanttoken`, `zac.objectenApi.token: objectentoken`, `zac.objecttypenApi.token: objecttypentoken` — API bearer tokens with obvious/guessable values shipped as defaults. _File: `values.yaml`, lines 2430, 2455, 2458._ Remediation: Replace with empty strings and add deployment-time validation.

---

### 3. Container Security Contexts

- [ ] **[Medium]** `adapter-deployment.yaml` has no `securityContext` at pod or container level — container may run as root, with full Linux capabilities, and a writable filesystem. _File: `templates/adapter-deployment.yaml`._ Remediation: Add `securityContext: { runAsNonRoot: true, allowPrivilegeEscalation: false, capabilities: { drop: [ALL] }, seccompProfile: { type: RuntimeDefault }, readOnlyRootFilesystem: true }` to the container spec.

- [ ] **[Medium]** `api-proxy-deployment.yaml` has no `securityContext` at pod or container level, and uses the upstream `nginx` image which runs as root (UID 0) by default. _File: `templates/api-proxy-deployment.yaml`._ Remediation: Switch the default image to `nginx:unprivileged` (or `nginxinc/nginx-unprivileged`) and add a container-level `securityContext` with `runAsNonRoot: true`, `allowPrivilegeEscalation: false`, `capabilities: { drop: [ALL] }`.

- [ ] **[Medium]** All Keycloak Jobs (`keycloak-ensure-operator-sa.yaml`, `keycloak-ensure-podiumd-admin-user.yaml`, `keycloak-import-master-realm-job.yaml`, `keycloak-import-podiumd-realm-job.yaml`) have no `securityContext` on any container or init container. These jobs have access to admin credentials via secrets. _Files: `templates/keycloak-ensure-operator-sa.yaml`, `templates/keycloak-ensure-podiumd-admin-user.yaml`, `templates/keycloak-import-master-realm-job.yaml`, `templates/keycloak-import-podiumd-realm-job.yaml`._ Remediation: Add `runAsNonRoot: true`, `allowPrivilegeEscalation: false`, `capabilities: { drop: [ALL] }` to all containers including init containers.

- [ ] **[Medium]** Seeding Jobs (`create-required-catalogi.yaml`, `create-required-objecttypen.yaml`) and the `redis-ha-label-master.yaml` Job have no `securityContext`. _Files: `templates/create-required-catalogi.yaml`, `templates/create-required-objecttypen.yaml`, `templates/redis-ha-label-master.yaml`._ Remediation: As above — add minimal security context to all container specs.

- [ ] **[Low]** No container in any custom template sets `readOnlyRootFilesystem: true`. While some containers genuinely need writable paths, this should be explicitly set (with `emptyDir` volume mounts for writable paths where needed) to reduce the blast radius of a container compromise. _Files: all templates with container specs._ Remediation: Audit each container for required writable paths; set `readOnlyRootFilesystem: true` and mount `emptyDir` volumes for any path that must be writable.

---

### 4. Network Exposure and NetworkPolicies

- [ ] **[Medium]** There are no `NetworkPolicy` resources anywhere in the chart. All pods in the namespace can communicate freely with each other, including with the Keycloak admin API and database endpoints. A single compromised pod can reach any other service. _Files: `templates/` (no NetworkPolicy templates found)._ Remediation: Add default-deny ingress/egress NetworkPolicies and explicit allow rules per component (e.g., only Keycloak Jobs may reach `keycloak-service:8080`, only designated pods may reach PostgreSQL).

- [ ] **[Low]** All Keycloak jobs communicate with Keycloak over unencrypted HTTP (`http://keycloak-service:8080`). Admin credentials (`ADMIN_PASS`, `CLIENT_SECRET`) are transmitted in plaintext within the cluster. _Files: `templates/keycloak-ensure-operator-sa.yaml`, `templates/keycloak-ensure-podiumd-admin-user.yaml`, `templates/keycloak-import-master-realm-job.yaml`, `templates/keycloak-import-podiumd-realm-job.yaml`._ Remediation: If mTLS (e.g. via a service mesh) is not in use, consider enabling Keycloak's HTTPS port for internal service-to-service calls and mounting a cluster CA cert in job containers.

---

### 5. API Proxy TLS Configuration

- [ ] **[Medium]** `apiproxy.locations.commonSettings.sslVerify: "off"` is the default for all upstream BAG/BRP/KVK proxy locations, disabling TLS certificate verification on government API backends. This opens the proxy to man-in-the-middle attacks against sensitive citizen data. _File: `values.yaml`, line 2757._ Remediation: Change default to `sslVerify: "on"` and add the required CA certificate via a mounted secret; the mTLS cert path (`nginxCertsSecret`) already exists for this purpose.

---

### 6. ServiceAccount Token Auto-mounting

- [ ] **[Medium]** `serviceAccount.automount: true` is the default for the shared `podiumd` ServiceAccount used by the adapter Deployment and seeding Jobs. This causes a Kubernetes API token to be auto-mounted into every pod using this SA, even those that do not need API access. _File: `values.yaml`, line 2900; `templates/serviceaccount.yaml`, line 12._ Remediation: Change the default to `automount: false` and add `automountServiceAccountToken: true` only on the specific Job pod specs that require it (currently none of the custom templates require API access except `redis-ha-label-master`, which has its own dedicated SA).

- [ ] **[Low]** `redis-ha-label-master` ServiceAccount has `automountServiceAccountToken: true` explicitly set. While this is intentional (the Job uses kubectl), it should be scoped to only the Job's pod spec (via pod-level override) rather than the ServiceAccount itself, to prevent accidental token mounting if the SA is reused. _File: `templates/redis-ha-label-master.yaml`, line 12._ Remediation: Set `automountServiceAccountToken: false` on the ServiceAccount and add `automountServiceAccountToken: true` on the Job's pod template spec.

---

### 7. Resource Limits — Missing on Seeding Jobs

- [ ] **[Medium]** The `create-required-catalogi` and `create-required-objecttypen` Jobs have no `resources` block on their containers, creating a denial-of-service risk where a runaway job could exhaust node resources. _Files: `templates/create-required-catalogi.yaml`, lines 398–420; `templates/create-required-objecttypen.yaml`, lines 97–128._ Remediation: Add `resources.requests` and `resources.limits` for CPU and memory, consistent with the values already defined for other jobs (e.g. `keycloak-operator.jobs.resources`).

---

### 8. Image Supply Chain

- [ ] **[Medium]** `redis-ha-label-master` uses `lachlanevenson/k8s-kubectl:v1.25.4` — an image from an individual (unofficial) Docker Hub maintainer running Kubernetes 1.25 (end-of-life). _File: `values.yaml`, line 427–428._ Remediation: Replace with an official or internally-mirrored kubectl image (e.g. `bitnami/kubectl` or a Dimpact ACR-mirrored equivalent). Ensure the tag aligns with the cluster Kubernetes version.

- [ ] **[Low]** `ita.poller.image.pullPolicy: Always` combined with a mutable semver tag (`3.0.0`) means every pod restart fetches the image from the registry without digest verification. If the tag is overwritten in the registry, a different image silently runs. _File: `values.yaml`, line 2881._ Remediation: Change to `IfNotPresent` (consistent with all other images in the chart) or pin the image with a `sha256:…` digest.

---

### 9. Keycloak Configuration

- [ ] **[Low]** `keycloak.config.adminOtpEnabled` defaults to `false`, meaning TOTP is not enforced for master-realm admin accounts by default. The podiumd realm enforces TOTP by default (line 45–49 of `keycloak-podiumd-realm-config.yaml`), but the master realm's admin accounts do not. _File: `values.yaml` (default inferred from conditional at `templates/keycloak-master-realm-config.yaml`, line 31)._ Remediation: Change the default to `true` or document prominently that this must be enabled in production; the master realm holds the Keycloak operator SA and bootstrap admin credentials.

- [ ] **[Low]** `keycloak.proxy.headers: "xforwarded"` and the builder init container set `KC_PROXY_HEADERS=xforwarded`. Keycloak trusts `X-Forwarded-*` headers from any caller; without a NetworkPolicy ensuring only the ingress controller can reach Keycloak's HTTP port, a compromised pod could forge client IP headers, potentially bypassing brute-force rate limits by spoofing `X-Forwarded-For`. _File: `values.yaml`, line 322; `templates/keycloak-cr.yaml`, line 20._ Remediation: In addition to the NetworkPolicy recommendation above, consider `headers: forwarded` (RFC 7239) if the ingress controller supports it, which is harder to spoof.

- [ ] **[Info]** The podiumd realm's `ssoSessionMaxLifespan` and `ssoSessionIdleTimeout` are not explicitly set in `keycloak-podiumd-realm-config.yaml`, leaving them at Keycloak defaults (10 hours and 30 minutes respectively). For an admin-only realm, shorter session lifespans are appropriate. _File: `templates/keycloak-podiumd-realm-config.yaml`._ Remediation: Explicitly set `ssoSessionMaxLifespan` (e.g. `36000` = 10 h, or shorter) and `ssoSessionIdleTimeout` to enforce session expiry consistently.

---

### 10. Miscellaneous

- [ ] **[Low]** Keycloak Jobs do not specify a `serviceAccountName`, so Kubernetes assigns the `default` ServiceAccount. If the `default` SA has been granted any RBAC permissions (common in misconfigured clusters), these jobs inherit them. _Files: `templates/keycloak-ensure-operator-sa.yaml`, `templates/keycloak-ensure-podiumd-admin-user.yaml`, `templates/keycloak-import-master-realm-job.yaml`, `templates/keycloak-import-podiumd-realm-job.yaml`._ Remediation: Explicitly set `serviceAccountName: {{ include "podiumd.serviceAccountName" . }}` (or a dedicated SA with no RBAC) in each Job pod spec, and ensure that SA has `automountServiceAccountToken: false`.

- [ ] **[Low]** `keycloak.http.httpEnabled: true` exposes Keycloak's HTTP port (8080) internally. While this is expected when TLS terminates at the ingress, there is no documented enforcement mechanism to ensure TLS is always terminated before Keycloak receives requests (e.g. the ingress `tls:` block, `keycloak.ingress.enabled: false` by default). If the Keycloak service is accidentally exposed via a LoadBalancer or misconfigured ingress, sessions would transit unencrypted. _File: `values.yaml`, line 163._ Remediation: Document this assumption explicitly in the chart README and consider a Helm `fail` guard that validates an ingress TLS host is set when `httpEnabled: true`.

- [ ] **[Info]** `adorsys/keycloak-config-cli:6.4.1-26` (used in realm import jobs) is sourced from the `adorsys` Docker Hub namespace. While well-established, it is a third-party image. Consider mirroring to ACR alongside other images and tracking it in `docs/images/`. _File: `values.yaml`, line 198._ Remediation: Mirror to the environment ACR; add to the images manifest process.
