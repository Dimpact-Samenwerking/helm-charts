# TLS Termination at Azure Application Gateway with cert-manager as Single Certificate Authority

**Solution design for PodiumD ingress — Dimpact**

| | |
|---|---|
| Status | Proposal |
| Date | 2026-06-10 |
| Applies to | `*-openzaak-in.dimpact.opengem.nl` and sibling ingress endpoints |
| Components | Azure Application Gateway v2 (WAF), APISIX, cert-manager, External Secrets Operator, Azure Key Vault, Azure DNS, FSC-NLX (Inway/Manager, §12) |

---

## 1. Summary

Application Gateway (AGW) remains the public TLS termination point and WAF for all incoming PodiumD traffic. cert-manager remains the **single source of truth for certificate issuance**: it obtains Let's Encrypt certificates via DNS-01, stores them as Kubernetes Secrets, and the **same certificate** is used by both APISIX (in-cluster, via `ApisixTls`) and AGW (via an automated push to Azure Key Vault).

Certificate rotation is fully automatic end to end:

```
cert-manager renews (T-30d before expiry)
   └─> Kubernetes Secret updated
         ├─> APISIX picks up new cert immediately (ApisixTls watch)
         └─> External Secrets Operator pushes PFX to Key Vault (≤1h)
               └─> AGW polls Key Vault and hot-reloads listener cert (≤4h)
```

No pipeline runs, no manual uploads, no certificate ever expires in only one of the two places.

The front-channel design is documented as two scenarios: **Scenario A** is the
configuration that is in place today; **Scenario B** is the target state that
this document proposes. The FSC system-to-system path (§12) is independent of
both.

### 1.1 Front-channel Scenario A — current state: AGW terminates, plain HTTP to in-cluster Gateway API

```
client
  │  HTTPS  (SNI: ontw-openzaak-in.dimpact.opengem.nl)
  ▼
Azure Application Gateway  ── terminates TLS (listener cert) + WAF
  │  HTTP :80  (unencrypted, host override: ontw-openzaak-in.dimpact.opengem.nl)
  ▼
Gateway API gateway (internal LoadBalancer)  ── HTTP listener, no TLS config
  │  HTTPRoute: host match → backendRef
  ▼
openzaak-nginx Service :80
  ▼
Open Zaak pods
```

TLS exists only on the public hop. The in-cluster gateway is a Kubernetes
**Gateway API** gateway (works identically whether the implementation behind
the `GatewayClass` is the APISIX ingress controller, Envoy Gateway, or
Cilium) with a plain HTTP listener — no certificate, no `ApisixTls`, no
cert-manager involvement on this path. Representative resources:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: podiumd-frontchannel
  namespace: podiumd
spec:
  gatewayClassName: apisix          # or envoy-gateway / cilium, per cluster
  listeners:
    - name: http
      protocol: HTTP                # <- no TLS termination in-cluster
      port: 80
      allowedRoutes:
        namespaces: { from: Same }
  infrastructure:
    annotations:
      service.beta.kubernetes.io/azure-load-balancer-internal: "true"
      service.beta.kubernetes.io/azure-load-balancer-internal-subnet: "snet-aks-ingress"
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: ontw-openzaak-in
  namespace: podiumd
spec:
  parentRefs:
    - name: podiumd-frontchannel
  hostnames:
    - ontw-openzaak-in.dimpact.opengem.nl   # matched against the Host header AGW forwards
  rules:
    - backendRefs:
        - name: openzaak-nginx
          port: 80
```

The matching AGW backend configuration (contrast with the HTTPS version in §7):

```hcl
backend_http_settings {
  name                  = "bhs-gwapi-http"
  protocol              = "Http"          # plaintext backend hop
  port                  = 80
  cookie_based_affinity = "Disabled"
  request_timeout       = 60
  host_name             = local.fqdn      # still required: drives HTTPRoute hostname matching
  probe_name            = "probe-ontw-openzaak-in-http"
}

probe {
  name                = "probe-ontw-openzaak-in-http"
  protocol            = "Http"
  host                = local.fqdn
  path                = "/"
  interval            = 30
  timeout             = 30
  unhealthy_threshold = 3
  match { status_code = ["200-399", "401"] }
}
```

**Properties of Scenario A:**

- *Simple and currently proven.* One certificate (on AGW), no in-cluster TLS
  material for the front channel, no sync machinery.
- *The AGW → gateway hop is unencrypted* across the VNet and node network.
  Whether that is acceptable depends on your BIO/risk assessment of the
  network segment: AGW and AKS in the same private VNet with NSGs is a
  contained path, but any TLS-everywhere or zero-trust requirement (and any
  future topology where the hop crosses a peering or shared segment) breaks it.
- *Certificate lifecycle lives outside the cluster.* The AGW listener cert is
  managed in Azure (manual upload or Key Vault) with no link to cert-manager —
  the exact split-lifecycle situation §1.2 removes.
- *Client identity:* the backend sees AGW's IP; the original client arrives in
  `X-Forwarded-For`, so the gateway/backends must be configured to trust XFF
  from the AGW subnet only (same `real-ip` consideration as §5.2).

### 1.2 Front-channel Scenario B — target state: end-to-end TLS with cert-manager as the single issuer

```
client
  │  HTTPS  (SNI: ontw-openzaak-in.dimpact.opengem.nl)
  ▼
Azure Application Gateway  ── terminates TLS (cert from Key Vault) + WAF
  │  HTTPS  (re-encrypted, host override: ontw-openzaak-in.dimpact.opengem.nl)
  ▼
APISIX (internal LoadBalancer)  ── presents the same LE cert via SNI
  │  HTTP   (in-cluster)
  ▼
openzaak-nginx Service :80
  ▼
Open Zaak pods
```

End-to-end encryption is preserved from the client up to the APISIX pod. The
final hop (APISIX → openzaak-nginx) is in-cluster HTTP; restrict it with
NetworkPolicies (see §9). Sections §3–§8 specify this scenario in full.

> The in-cluster termination in Scenario B is written against APISIX's native
> CRDs (`ApisixTls`/`ApisixRoute`, §5) to match the current podiumd charts.
> The same design works unchanged with Gateway API resources if you prefer to
> keep the Scenario A object model: an HTTPS listener on the `Gateway` with
> `certificateRefs` pointing at the cert-manager Secret, plus the same
> `HTTPRoute` — only §5 changes, §4 and §6–§8 are identical.

### 1.3 Migration path A → B

Scenario B is a strict superset of A's moving parts, so migration is additive
and can be done per endpoint with no downtime:

1. Deploy §4 (Certificate) and §5 (`ApisixTls`, or a TLS listener on the
   existing `Gateway` with `certificateRefs`) — the in-cluster gateway now
   serves HTTPS on 443 *in addition to* the existing HTTP listener on 80.
2. Deploy §6 (PushSecret) and confirm the certificate lands in Key Vault.
3. Switch the AGW listener's certificate reference to the synced Key Vault
   cert (versionless secret URI, §7).
4. Create the HTTPS backend settings + probe from §7 alongside the existing
   HTTP ones, and flip the routing rule from `bhs-gwapi-http` to
   `bhs-apisix-https`. Rollback is flipping the rule back.
5. After soak, remove the HTTP listener (or keep it for cluster-internal
   callers) and the old backend settings.

---

## 2. Design decisions

| Decision | Choice | Rationale |
|---|---|---|
| Public TLS termination | Application Gateway | Keeps WAF inspection, L7 routing, Azure-native logging/metrics |
| Certificate issuer | cert-manager + Let's Encrypt | Already in use; GitOps-native; free; 90-day forced rotation hygiene |
| ACME challenge type | **DNS-01 via Azure DNS** | Independent of the ingress path — no port-80 challenge routing through AGW/WAF; enables wildcards |
| Cert distribution to AGW | External Secrets Operator `PushSecret` → Key Vault | Declarative, watches the Secret, no CronJob scheduling gap; AGW Key Vault integration handles hot-reload |
| AGW → APISIX leg | HTTPS with hostname override, **certificate validation on** | The backend presents a publicly trusted LE cert for the exact FQDN, so AGW validates it with zero extra trust configuration |
| APISIX → openzaak-nginx leg | HTTP (in-cluster) | Standard pattern; harden with NetworkPolicy. Optionally upgrade to private-CA mTLS later |

### Why not the alternatives

- **Keeping Scenario A (plain HTTP backend hop) permanently:** viable while AGW
  and AKS share a contained private VNet, but it leaves an unencrypted segment
  carrying citizen data on the node network, keeps the public certificate
  lifecycle manual/out-of-cluster, and fails any TLS-everywhere baseline.
  Documented as the current state in §1.1 with a no-downtime migration in §1.3.
- **TLS passthrough (AGW L4 TCP listener → APISIX terminates):** purest "APISIX owns the cert" model and requires no Key Vault sync, but AGW can no longer see the HTTP layer — **no WAF, no host/path routing**, and client IPs require Proxy Protocol v1 on both sides. Rejected for internet-facing citizen-data APIs (but exactly right for the FSC path, §12).
- **Split certificates (AGW uses its own wildcard from Key Vault):** robust and conventional, but creates a second certificate lifecycle outside GitOps and the in-cluster cert no longer matches the public one. Keep as fallback if pushing private keys from the cluster to Key Vault is rejected by your security baseline (check against BIO; see §9).

### Scenario comparison (front channel)

| | **A — current** (AGW → HTTP → Gateway API) | **B — target** (AGW → HTTPS → APISIX/Gateway) |
|---|---|---|
| Public TLS + WAF | ✔ AGW | ✔ AGW (unchanged) |
| AGW → cluster hop | Plain HTTP :80 | TLS, certificate validation **on** |
| In-cluster certificate | none | cert-manager LE cert via `ApisixTls` / `certificateRefs` |
| AGW listener cert lifecycle | Manual / out-of-cluster | cert-manager → ESO → Key Vault, fully automatic |
| Rotation risk | Human-dependent (annual scramble) | Automated, ~29 days slack (§8) |
| Extra components | — | ESO `PushSecret` (or Python CronJob, §6.3) |
| BIO / TLS-everywhere fit | Conditional on VNet containment | Yes, up to the gateway pod |

---

## 3. Prerequisites

- AKS cluster with **workload identity** (OIDC issuer) enabled.
- cert-manager ≥ v1.14 installed (you already run this).
- External Secrets Operator ≥ v0.10 installed (`helm repo add external-secrets https://charts.external-secrets.io`).
- Azure DNS zone `dimpact.opengem.nl` (or a delegated child zone for ACME, see §4.3).
- Azure Key Vault, e.g. `kv-dimpact-podiumd-ontw`.
- Application Gateway v2 (WAF_v2 SKU) with a user-assigned managed identity.
- APISIX exposed via an **internal** LoadBalancer Service in the AGW's VNet (or a peered VNet).

### Azure identities and role assignments

Three identities, least privilege each:

| Identity | Used by | Role | Scope |
|---|---|---|---|
| `id-certmanager-dns` (workload identity) | cert-manager pods | `DNS Zone Contributor` | DNS zone `dimpact.opengem.nl` |
| `id-eso-kv-push` (workload identity) | External Secrets Operator | `Key Vault Certificates Officer` | Key Vault `kv-dimpact-podiumd-ontw` |
| `id-agw` (user-assigned MI) | Application Gateway | `Key Vault Secrets User` | Key Vault `kv-dimpact-podiumd-ontw` |

```bash
# Federated credential for cert-manager (repeat analogously for ESO)
AKS_OIDC_ISSUER=$(az aks show -g rg-podiumd-ontw -n aks-podiumd-ontw \
  --query oidcIssuerProfile.issuerUrl -o tsv)

az identity federated-credential create \
  --name certmanager-fed \
  --identity-name id-certmanager-dns \
  --resource-group rg-podiumd-ontw \
  --issuer "${AKS_OIDC_ISSUER}" \
  --subject "system:serviceaccount:cert-manager:cert-manager" \
  --audiences api://AzureADTokenExchange
```

> **Note — AGW reads certificates as secrets.** Key Vault stores a certificate's
> private key + chain behind a *secret* of the same name; AGW fetches that secret,
> which is why its role is `Key Vault Secrets User` and not a certificates role.

---

## 4. cert-manager: DNS-01 issuance

### 4.1 ClusterIssuer (Azure DNS, workload identity)

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod-dns01
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: beheer@dimpact.nl
    privateKeySecretRef:
      name: letsencrypt-prod-dns01-account-key
    solvers:
      - dns01:
          azureDNS:
            subscriptionID: "<subscription-id>"
            resourceGroupName: rg-dns-dimpact
            hostedZoneName: dimpact.opengem.nl
            environment: AzurePublicCloud
            managedIdentity:
              clientID: "<client-id-of-id-certmanager-dns>"
        # Optionally scope this solver:
        # selector:
        #   dnsZones: ["dimpact.opengem.nl"]
```

cert-manager's ServiceAccount must carry the workload-identity annotations
(values for the official Helm chart):

```yaml
serviceAccount:
  annotations:
    azure.workload.identity/client-id: "<client-id-of-id-certmanager-dns>"
podLabels:
  azure.workload.identity/use: "true"
```

### 4.2 Certificate

One `Certificate` per public endpoint (or a wildcard — see 4.3). The
`Usages` and a stable `commonName` keep the PFX import into Key Vault clean.

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: ontw-openzaak-in
  namespace: podiumd
spec:
  secretName: ontw-openzaak-in-tls
  commonName: ontw-openzaak-in.dimpact.opengem.nl
  dnsNames:
    - ontw-openzaak-in.dimpact.opengem.nl
  duration: 2160h      # 90d (LE maximum)
  renewBefore: 720h    # renew at T-30d — leaves ample slack for the KV/AGW propagation chain
  privateKey:
    algorithm: RSA     # AGW accepts ECDSA too; RSA-2048 is the most friction-free for PFX import
    size: 2048
    rotationPolicy: Always
  issuerRef:
    name: letsencrypt-prod-dns01
    kind: ClusterIssuer
```

### 4.3 Optional: dedicated ACME delegation zone

If the DNS team is reluctant to grant `DNS Zone Contributor` on the production
zone, delegate only the challenge records:

```
_acme-challenge.ontw-openzaak-in.dimpact.opengem.nl.  CNAME  ontw-openzaak-in.acme.dimpact-aks.nl.
```

and point the solver (with `cnameStrategy: Follow`) at the `acme.dimpact-aks.nl`
zone, which cert-manager's identity can fully control without touching
`dimpact.opengem.nl`.

---

## 5. APISIX: SNI certificate and routing

### 5.1 ApisixTls — bind the cert-manager Secret to the SNI

```yaml
apiVersion: apisix.apache.org/v2
kind: ApisixTls
metadata:
  name: ontw-openzaak-in
  namespace: podiumd
spec:
  hosts:
    - ontw-openzaak-in.dimpact.opengem.nl
  secret:
    name: ontw-openzaak-in-tls
    namespace: podiumd
```

The APISIX ingress controller watches the Secret; a cert-manager renewal is
live on the APISIX data plane within seconds — no restart.

### 5.2 ApisixRoute — host-based routing to openzaak-nginx

```yaml
apiVersion: apisix.apache.org/v2
kind: ApisixRoute
metadata:
  name: ontw-openzaak-in
  namespace: podiumd
spec:
  http:
    - name: openzaak
      match:
        hosts:
          - ontw-openzaak-in.dimpact.opengem.nl
        paths:
          - "/*"
      backends:
        - serviceName: openzaak-nginx
          servicePort: 80
      plugins:
        # Preserve the original client IP that AGW forwards.
        # AGW always appends the client IP to X-Forwarded-For.
        - name: real-ip
          enable: true
          config:
            source: http_x_forwarded_for
            recursive: true
            # Trust only the AGW subnet as XFF source:
            trusted_addresses: ["10.20.4.0/24"]   # <- AGW subnet CIDR
```

### 5.3 APISIX exposure — internal LoadBalancer

APISIX must be reachable from the AGW subnet on a **stable private IP**
(AGW backend pools target IPs/FQDNs, and a stable IP keeps the pool static):

```yaml
# values override for the APISIX (sub)chart
apisix:
  service:
    type: LoadBalancer
    annotations:
      service.beta.kubernetes.io/azure-load-balancer-internal: "true"
      service.beta.kubernetes.io/azure-load-balancer-internal-subnet: "snet-aks-ingress"
    loadBalancerIP: 10.20.8.10   # reserve in the subnet; referenced by the AGW backend pool
```

---

## 6. Certificate push to Key Vault (External Secrets Operator)

### 6.1 ClusterSecretStore — Key Vault via workload identity

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ClusterSecretStore
metadata:
  name: azure-kv-dimpact-ontw
spec:
  provider:
    azurekv:
      authType: WorkloadIdentity
      vaultUrl: https://kv-dimpact-podiumd-ontw.vault.azure.net
      serviceAccountRef:
        name: external-secrets
        namespace: external-secrets
```

ESO's ServiceAccount carries the `azure.workload.identity/client-id`
annotation for `id-eso-kv-push`, analogous to §4.1.

### 6.2 PushSecret — TLS Secret → Key Vault *certificate*

The crucial detail: push with `type: secret` omitted and the
`tls.crt`/`tls.key` pair targeted as a **certificate object**, so Key Vault
versions it and AGW can consume it. ESO assembles the PKCS#12 bundle for you
when the remote object type is a certificate:

```yaml
apiVersion: external-secrets.io/v1alpha1
kind: PushSecret
metadata:
  name: ontw-openzaak-in-to-akv
  namespace: podiumd
spec:
  refreshInterval: 1h
  secretStoreRefs:
    - name: azure-kv-dimpact-ontw
      kind: ClusterSecretStore
  selector:
    secret:
      name: ontw-openzaak-in-tls
  template:
    type: kubernetes.io/tls
  data:
    - match:
        secretKey: tls.crt          # ESO pairs this with tls.key from the same Secret
      metadata:
        apiVersion: kubernetes.external-secrets.io/v1alpha1
        kind: PushSecretMetadata
        spec:
          targetType: Certificate    # import as KV *certificate*, not a raw secret
      remoteRef:
        remoteKey: ontw-openzaak-in  # Key Vault certificate name referenced by AGW
```

Each cert-manager renewal produces a **new Key Vault certificate version**
under the same name; AGW always follows the latest version (§7).

### 6.3 Alternative: Python sync CronJob (if ESO is not desired)

A minimal, dependency-light equivalent. Runs under the same workload identity
(`id-eso-kv-push`), idempotent — it imports only when the certificate in the
cluster differs from the latest Key Vault version.

```python
"""Sync a cert-manager TLS Secret to an Azure Key Vault certificate.

Idempotent: compares the leaf certificate's SHA-1 thumbprint against the
latest Key Vault version and imports only on change. Intended to run as a
CronJob with Azure Workload Identity (no client secrets anywhere).
"""
import base64
import os

from azure.identity import DefaultAzureCredential
from azure.keyvault.certificates import CertificateClient, CertificatePolicy
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from kubernetes import client, config

NAMESPACE = os.environ["SECRET_NAMESPACE"]        # e.g. "podiumd"
SECRET_NAME = os.environ["SECRET_NAME"]           # e.g. "ontw-openzaak-in-tls"
VAULT_URL = os.environ["VAULT_URL"]               # e.g. "https://kv-....vault.azure.net"
KV_CERT_NAME = os.environ["KV_CERT_NAME"]         # e.g. "ontw-openzaak-in"


def load_tls_secret() -> tuple[bytes, bytes]:
    """Read tls.crt / tls.key (PEM) from the in-cluster Secret."""
    config.load_incluster_config()
    secret = client.CoreV1Api().read_namespaced_secret(SECRET_NAME, NAMESPACE)
    return (
        base64.b64decode(secret.data["tls.crt"]),
        base64.b64decode(secret.data["tls.key"]),
    )


def build_pfx(cert_pem: bytes, key_pem: bytes) -> tuple[bytes, str]:
    """Assemble an unencrypted PKCS#12 bundle (leaf + chain) for KV import.

    Returns the PFX bytes and the leaf's SHA-1 thumbprint (hex, upper) —
    the same thumbprint format Key Vault exposes on certificate versions.
    """
    chain = x509.load_pem_x509_certificates(cert_pem)   # [leaf, *intermediates]
    leaf, intermediates = chain[0], chain[1:]
    key = serialization.load_pem_private_key(key_pem, password=None)
    pfx = pkcs12.serialize_key_and_certificates(
        name=KV_CERT_NAME.encode(),
        key=key,
        cert=leaf,
        cas=intermediates or None,
        encryption_algorithm=serialization.NoEncryption(),  # TLS within Azure; KV encrypts at rest
    )
    return pfx, leaf.fingerprint(hashes.SHA1()).hex().upper()


def main() -> None:
    cert_pem, key_pem = load_tls_secret()
    pfx, thumbprint = build_pfx(cert_pem, key_pem)

    kv = CertificateClient(VAULT_URL, DefaultAzureCredential())
    try:
        current = kv.get_certificate(KV_CERT_NAME)
        if current.properties.x509_thumbprint.hex().upper() == thumbprint:
            print(f"{KV_CERT_NAME}: Key Vault already at {thumbprint}; nothing to do.")
            return
    except Exception:
        pass  # first import — certificate does not exist yet

    kv.import_certificate(
        certificate_name=KV_CERT_NAME,
        certificate_bytes=pfx,
        policy=CertificatePolicy(exportable=True, content_type="application/x-pkcs12"),
    )
    print(f"{KV_CERT_NAME}: imported new version {thumbprint}.")


if __name__ == "__main__":
    main()
```

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: kv-cert-sync-ontw-openzaak-in
  namespace: podiumd
spec:
  schedule: "*/30 * * * *"
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      template:
        metadata:
          labels:
            azure.workload.identity/use: "true"
        spec:
          serviceAccountName: kv-cert-sync   # annotated with the id-eso-kv-push client-id
          restartPolicy: Never
          containers:
            - name: sync
              image: <acr>/kv-cert-sync:1.0.0
              env:
                - { name: SECRET_NAMESPACE, value: podiumd }
                - { name: SECRET_NAME,      value: ontw-openzaak-in-tls }
                - { name: VAULT_URL,        value: "https://kv-dimpact-podiumd-ontw.vault.azure.net" }
                - { name: KV_CERT_NAME,     value: ontw-openzaak-in }
              securityContext:
                runAsNonRoot: true
                allowPrivilegeEscalation: false
                readOnlyRootFilesystem: true
                capabilities: { drop: [ALL] }
                seccompProfile: { type: RuntimeDefault }
```

> The ServiceAccount needs a Role granting `get` on exactly this Secret —
> not blanket Secret read in the namespace.

---

## 7. Application Gateway configuration

Terraform fragment for the `ontw-openzaak-in` endpoint. The same pattern
repeats per endpoint; in practice you would wrap it in a `for_each` over a
map of endpoints.

```hcl
locals {
  fqdn        = "ontw-openzaak-in.dimpact.opengem.nl"
  kv_cert_id  = "https://kv-dimpact-podiumd-ontw.vault.azure.net/secrets/ontw-openzaak-in"
  # NOTE: versionless *secret* URI — AGW reads the cert via its secret endpoint
  # and follows the latest version automatically on rotation.
  apisix_ip   = "10.20.8.10"
}

resource "azurerm_application_gateway" "podiumd" {
  # ... sku WAF_v2, autoscale, gateway_ip_configuration, frontend config ...

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.agw.id]   # Key Vault Secrets User on the KV
  }

  # --- Certificate, hot-reloaded from Key Vault ---
  ssl_certificate {
    name                = "ontw-openzaak-in"
    key_vault_secret_id = local.kv_cert_id
  }

  # --- Public listener ---
  http_listener {
    name                           = "lsn-ontw-openzaak-in"
    frontend_ip_configuration_name = "public-frontend"
    frontend_port_name             = "port-443"
    protocol                       = "Https"
    host_name                      = local.fqdn          # multi-site listener: SNI routing
    ssl_certificate_name           = "ontw-openzaak-in"
    firewall_policy_id             = azurerm_web_application_firewall_policy.podiumd.id
  }

  # --- Backend: APISIX internal LB ---
  backend_address_pool {
    name         = "pool-apisix"
    ip_addresses = [local.apisix_ip]
  }

  backend_http_settings {
    name                                = "bhs-apisix-https"
    protocol                            = "Https"
    port                                = 443
    cookie_based_affinity               = "Disabled"
    request_timeout                     = 60
    host_name                           = local.fqdn   # !! SNI + Host towards APISIX
    pick_host_name_from_backend_address = false
    probe_name                          = "probe-ontw-openzaak-in"
    # No trusted_root_certificate: the backend presents a publicly trusted
    # Let's Encrypt cert for local.fqdn, so AGW's default CA validation passes.
    # Do NOT set trust_backend_server_certificate workarounds — validation stays ON.
  }

  probe {
    name                = "probe-ontw-openzaak-in"
    protocol            = "Https"
    host                = local.fqdn
    path                = "/"          # or a cheap health path exposed via an ApisixRoute
    interval            = 30
    timeout             = 30
    unhealthy_threshold = 3
    match { status_code = ["200-399", "401"] }   # Open Zaak root may 401 — that still proves the chain
  }

  request_routing_rule {
    name                       = "rule-ontw-openzaak-in"
    priority                   = 100
    rule_type                  = "Basic"
    http_listener_name         = "lsn-ontw-openzaak-in"
    backend_address_pool_name  = "pool-apisix"
    backend_http_settings_name = "bhs-apisix-https"
  }

  ssl_policy {
    policy_type = "Predefined"
    policy_name = "AppGwSslPolicy20220101S"   # TLS 1.2+ with modern ciphers
  }
}
```

Key points worth restating:

1. **Versionless Key Vault secret URI** (`/secrets/<name>`, no version suffix) —
   AGW polls Key Vault (~every 4 hours) and hot-swaps the listener certificate
   when ESO pushes a new version. With a versioned URI rotation would silently stop.
2. **`host_name` on the backend settings** — this drives both SNI (so APISIX's
   `ApisixTls` matches) and the `Host` header (so the `ApisixRoute` matches).
   Without it, APISIX serves its default cert and AGW marks the backend unhealthy.
3. **Backend certificate validation stays enabled.** Because the in-cluster
   cert is publicly trusted and matches the FQDN, no `trusted_root_certificate`
   is needed and no validation bypass should ever be configured.
4. **Custom probe with `host`** — default probes use the backend IP as host
   and would fail both SNI matching and certificate validation.

### DNS

```
ontw-openzaak-in.dimpact.opengem.nl.  A  <AGW public frontend IP>
# or, if the AGW has an Azure-assigned DNS name:
ontw-openzaak-in.dimpact.opengem.nl.  CNAME  <agw-name>.<region>.cloudapp.azure.com.
```

The DNS-01 issuance in §4 is independent of this record, so the certificate
can be issued **before** the endpoint goes live — useful for staged rollouts.

---

## 8. Rotation timeline and failure windows

| T | Event |
|---|---|
| T0 | cert-manager renews at 60 days (renewBefore 30d). Secret `ontw-openzaak-in-tls` updated |
| T0 + seconds | APISIX serves the new certificate (controller watch) |
| T0 + ≤1h | ESO `PushSecret` refresh interval fires → new Key Vault certificate version |
| T0 + ≤5h | AGW Key Vault poll (≤4h after the push) → listener serves the new certificate |

During the window T0 → T0+5h, AGW still serves the *previous* certificate while
APISIX already presents the new one. Both are valid (the old one has ~30 days
left), and AGW's backend validation only requires *a* trusted, name-matching
cert — so **the overlap is harmless by construction**. Total propagation slack
versus expiry: ~29 days.

**Monitoring (do not skip):**

- Alert on Key Vault certificate `expires_at < 21d` (Azure Monitor) — catches a
  broken push chain while cert-manager has already renewed in-cluster.
- Alert on cert-manager `certmanager_certificate_expiration_timestamp_seconds`
  `< 14d` (Prometheus — you already scrape this stack via monitoring-logging).
- AGW backend health: alert on `UnhealthyHostCount > 0` for `pool-apisix`.
- Blackbox probe on `https://ontw-openzaak-in.dimpact.opengem.nl` validating
  the certificate chain and expiry from the outside.

---

## 9. Security considerations

- **Private key egress.** The LE private key leaves the cluster (Secret → Key Vault).
  Transport is TLS to Key Vault; at rest it is HSM-backed. Verify acceptability
  against your BIO/NCSC baseline. If unacceptable → fall back to the split-certificate
  model (AGW gets its own Key Vault-managed certificate; cert-manager issues a
  private-CA cert for the AGW→APISIX leg, uploaded to AGW as trusted root).
- **Least privilege.** The push identity holds `Key Vault Certificates Officer`
  on one vault only; it cannot read other secrets. The AGW identity can only
  *read* secrets. cert-manager's identity touches only the DNS zone (or only
  the delegated ACME zone, §4.3).
- **Key Vault hardening.** Enable purge protection and soft delete; restrict
  network access to the AKS egress and AGW subnets via Key Vault firewall;
  enable diagnostic logging of certificate imports (audit trail for every rotation).
- **No validation bypasses.** Backend certificate validation on AGW must remain
  enabled (§7 point 3) — this mirrors the `proxy_ssl_verify` finding from the
  chart review: never let a missing cert default to "don't verify".
- **NetworkPolicies.** Pair this design with the deferred NetworkPolicy work:
  `openzaak-nginx` should accept ingress **only from APISIX pods**, so the
  plaintext in-cluster hop cannot be reached laterally.
- **WAF.** Keep the WAF policy in Prevention mode on the listener; tune
  OWASP CRS exclusions for Open Zaak's JSON bodies on a per-rule basis rather
  than disabling rule groups.

---

## 10. Rollout plan

1. **Prepare identities and Key Vault** (§3) — no traffic impact.
2. **Deploy the ClusterIssuer and one Certificate** for `ontw-openzaak-in` (§4).
   Verify: `kubectl get certificate -n podiumd` shows `Ready=True`.
3. **Bind the cert in APISIX** (`ApisixTls`, §5.1) and verify in-cluster:
   `openssl s_client -connect 10.20.8.10:443 -servername ontw-openzaak-in.dimpact.opengem.nl`
   must return the LE chain.
4. **Deploy ESO store + PushSecret** (§6). Verify the certificate appears in
   Key Vault with the expected thumbprint.
5. **Configure the AGW listener/backend/probe** (§7) pointing at the existing
   APISIX IP. Verify backend health turns green.
6. **Cut over DNS** for `ontw-openzaak-in.dimpact.opengem.nl` to the AGW frontend.
7. **Force a rotation test**: `cmctl renew ontw-openzaak-in -n podiumd`, then
   confirm the new thumbprint propagates to APISIX (immediately), Key Vault (≤1h),
   and the public endpoint (≤5h).
8. **Roll out to the remaining endpoints** by repeating §4–§7 per FQDN
   (Terraform `for_each` + a values-driven loop over `Certificate`/`ApisixTls`/
   `ApisixRoute` in the podiumd chart).

---

## 11. Troubleshooting quick reference

| Symptom | Likely cause | Check |
|---|---|---|
| AGW backend unhealthy, probe "certificate mismatch" | Missing `host_name` on backend settings or probe | §7 points 2 & 4 |
| APISIX serves its default self-signed cert to AGW | `ApisixTls` hosts don't match the SNI sent by AGW | `kubectl describe apisixtls`; confirm backend `host_name` |
| Certificate renewed in cluster but AGW serves the old one > 5h | Versioned KV URI, or push chain broken | §7 point 1; ESO `PushSecret` status; KV versions list |
| `PushSecret` errors `403` | Missing `Key Vault Certificates Officer` or federated credential subject mismatch | §3 role table; `kubectl describe pushsecret` |
| DNS-01 order stuck `pending` | Identity lacks DNS Zone Contributor, or CNAME delegation broken | `kubectl describe challenge`; `dig _acme-challenge.<fqdn> TXT` |
| Clients see AGW cert but APISIX routes 404 | Listener forwards but `ApisixRoute` host mismatch | Host header override vs. route `match.hosts` |

---

## 12. FSC (Federatieve Service Connectiviteit) integration

### 12.1 Scope: which traffic FSC governs

FSC (Logius standard; reference implementation **FSC-NLX**) standardizes
**system-to-system API traffic between organizations** (Peers): another
municipality, a supplier, or a ketenpartner whose systems call your ZGW APIs
through their **Outway**, landing on your **Inway**. FSC-Core mandates, per
normative requirement:

- **mTLS everywhere between FSC components** — Outway → Inway and
  Manager ↔ Manager connections use mutual TLS with X.509 certificates signed
  by the Group's chosen **Trust Anchor** (in Dutch government groups in
  practice: PKIoverheid private services certificates carrying the OIN as
  Peer ID). Let's Encrypt certificates are **not** valid on this path.
- **The Inway is the entry point** — a reverse proxy that accepts *only* mTLS
  connections from Outways with a Trust Anchor certificate, validates the
  access token in the `Fsc-Authorization` header against signed Contracts
  (ServiceConnectionGrants), and writes FSC transaction logs.
- **A Manager negotiates Contracts** and issues access tokens; it is reachable
  by peer Managers over mTLS as well.

Two consequences for this design:

1. **The front-channel paths (Scenarios A and B, §1–§7) are out of FSC scope.**
   Front-channel traffic — citizens and employees in browsers, OIDC flows to
   Keycloak, PodiumD frontends — has no Outway on the client side; FSC does
   not apply to it. AGW L7 termination + WAF + Let's Encrypt remains the right
   construction there.
2. **AGW must NOT terminate TLS on the FSC path.** The Inway authenticates
   the Outway by its client certificate and validates token binding against
   it; an AGW HTTPS listener in between breaks the Outway↔Inway mTLS chain,
   and forwarding the client certificate in a header is not spec-compliant.
   The FSC path therefore uses the AGW **Layer 4 TCP listener in passthrough
   mode** (no certificate configured on the listener; encrypted bytes are
   relayed unmodified).

The WAF trade-off of L4 passthrough is acceptable here by design: the Inway
*is* the FSC-mandated security control (trust-anchor authentication,
contract-based authorization, standardized logging) and only accepts traffic
from contractually authorized, certificate-authenticated peers.

### 12.2 Combined architecture

```
Front-channel (browsers, OIDC)                      FSC system-to-system (peers)
──────────────────────────────                      ────────────────────────────
client                                              peer Outway
  │ HTTPS (SNI: ontw-openzaak-in...)                  │ mTLS (Trust Anchor / PKIO certs)
  ▼                                                   ▼
AGW L7 listener :443  ── WAF, terminates ──         AGW L4 TCP listener :8443 ── passthrough,
  │ HTTPS re-encrypt                                  │ no termination, no WAF
  ▼                                                   ▼
APISIX (10.20.8.10)                                 FSC Inway (10.20.8.11) ── terminates mTLS,
  │                                                   │ validates contract + Fsc-Authorization
  ▼                                                   ▼
openzaak-nginx :80  ◄────────────────────────────────┘
        (NetworkPolicy: ingress from APISIX pods + Inway pods only)

FSC Manager (10.20.8.12) ── AGW L4 TCP listener :9443, passthrough,
                            mTLS with peer Managers (contract negotiation)
```

> **Hostnames.** e.g. `fsc-inway.dimpact.opengem.nl` → AGW frontend, port 8443
> and `fsc-manager.dimpact.opengem.nl` → port 9443. L4 listeners cannot do
> SNI-based multi-site routing, so each FSC endpoint gets its **own frontend
> port** (or its own frontend IP). Document the port in the Directory entry.

### 12.3 AGW Layer 4 passthrough listeners (Terraform)

```hcl
locals {
  inway_ip   = "10.20.8.11"
  manager_ip = "10.20.8.12"
}

resource "azurerm_application_gateway" "podiumd" {
  # ... existing L7 config from §7 remains unchanged ...

  # --- FSC frontend ports ---
  frontend_port { name = "port-8443" ; port = 8443 }   # Inway
  frontend_port { name = "port-9443" ; port = 9443 }   # Manager

  # --- L4 TCP listeners: NO ssl_certificate => passthrough, mTLS reaches the Inway intact ---
  listener {
    name                           = "lsn-fsc-inway"
    frontend_ip_configuration_name = "public-frontend"
    frontend_port_name             = "port-8443"
    protocol                       = "Tcp"
  }
  listener {
    name                           = "lsn-fsc-manager"
    frontend_ip_configuration_name = "public-frontend"
    frontend_port_name             = "port-9443"
    protocol                       = "Tcp"
  }

  backend_address_pool { name = "pool-fsc-inway"   ; ip_addresses = [local.inway_ip] }
  backend_address_pool { name = "pool-fsc-manager" ; ip_addresses = [local.manager_ip] }

  backend_settings {
    name     = "bs-fsc-inway"
    protocol = "Tcp"          # raw relay; the Inway terminates mTLS itself
    port     = 8443
    probe_name = "probe-fsc-inway"
    timeout    = 60
    # Optional: proxy protocol v1 to preserve client IPs in Inway logs.
    # Enable ONLY if the Inway listener is configured to parse it.
  }
  backend_settings {
    name       = "bs-fsc-manager"
    protocol   = "Tcp"
    port       = 9443
    probe_name = "probe-fsc-manager"
    timeout    = 60
  }

  # TCP health probes — a TLS handshake probe would need a TA client cert,
  # which AGW cannot present; TCP connect suffices for liveness.
  probe { name = "probe-fsc-inway"   ; protocol = "Tcp" ; port = 8443 ; interval = 30 ; timeout = 30 ; unhealthy_threshold = 3 }
  probe { name = "probe-fsc-manager" ; protocol = "Tcp" ; port = 9443 ; interval = 30 ; timeout = 30 ; unhealthy_threshold = 3 }

  routing_rule {
    name                       = "rule-fsc-inway"
    priority                   = 200
    rule_type                  = "Basic"
    listener_name              = "lsn-fsc-inway"
    backend_address_pool_name  = "pool-fsc-inway"
    backend_settings_name      = "bs-fsc-inway"
  }
  routing_rule {
    name                       = "rule-fsc-manager"
    priority                   = 210
    rule_type                  = "Basic"
    listener_name              = "lsn-fsc-manager"
    backend_address_pool_name  = "pool-fsc-manager"
    backend_settings_name      = "bs-fsc-manager"
  }
}
```

> **Provider note.** L4 (`listener`/`backend_settings`/`routing_rule` TCP
> blocks) requires a recent `azurerm` provider; on older versions fall back to
> `azapi` for the L4 resources. Verify attribute names against the provider
> version in use — L4 support is newer than the L7 schema and has shifted
> between releases.

### 12.4 FSC-NLX deployment alongside the podiumd chart

Certificates first — this path deliberately bypasses the §4–§6 ACME/Key Vault
flow:

| Certificate | Issued by | Lifecycle |
|---|---|---|
| Inway/Manager external (mTLS server+client) | Group Trust Anchor (PKIoverheid private services, OIN in subject) | Out-of-band issuance (CSR → TSP); mounted as a Secret; **monitored** by the same expiry alerting as §8 |
| Internal organization certs (Inway↔Manager↔controller) | Internal CA — cert-manager **CA issuer** is fine here | Fully automated in-cluster |

```yaml
# Trust-anchor material, created out-of-band (kubectl create secret tls ... + CA bundle)
apiVersion: v1
kind: Secret
metadata:
  name: fsc-inway-external-tls       # PKIO private cert + key
  namespace: fsc
type: kubernetes.io/tls
stringData: {}                        # populated via sealed-secrets / SOPS, never in git plaintext
---
# cert-manager still watches expiry, without issuing:
# alert on certmanager_certificate_expiration... does NOT cover this Secret —
# add a kube-prometheus rule on x509 exporter or a blackbox TLS probe (see 12.6).
```

Inway and Manager via the FSC-NLX Helm charts (values sketch; align versions
with the Group's FSC profile):

```yaml
# values-fsc-inway.yaml
inway:
  name: podiumd-ontw
  selfAddress: "fsc-inway.dimpact.opengem.nl:8443"
  tls:
    externalSecretName: fsc-inway-external-tls     # Trust Anchor cert
    internalSecretName: fsc-inway-internal-tls     # cert-manager CA issuer
service:
  type: LoadBalancer
  annotations:
    service.beta.kubernetes.io/azure-load-balancer-internal: "true"
    service.beta.kubernetes.io/azure-load-balancer-internal-subnet: "snet-aks-ingress"
  loadBalancerIP: 10.20.8.11
podSecurityContext:                                 # same baseline as podiumd templates
  runAsNonRoot: true
  seccompProfile: { type: RuntimeDefault }
containerSecurityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities: { drop: [ALL] }
```

The Inway's **service registration** then routes the FSC service to the same
backend APISIX uses:

```yaml
# Service definition registered with the Manager (FSC service catalog entry)
services:
  - name: open-zaak
    endpointURL: "http://openzaak-nginx.podiumd.svc.cluster.local:80"
    documentationURL: "https://ontw-openzaak-in.dimpact.opengem.nl/api/v1/schema"
    apiSpecificationURL: "http://openzaak-nginx.podiumd.svc.cluster.local/api/v1/schema/openapi.yaml"
    internal: false      # discoverable in the Group Directory
```

### 12.5 NetworkPolicies — dual ingress to openzaak-nginx

`openzaak-nginx` now has exactly two legitimate callers. Default-deny plus:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: openzaak-nginx-ingress
  namespace: podiumd
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: openzaak-nginx
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector:                       # 1) APISIX data plane (front-channel, §5)
            matchLabels:
              app.kubernetes.io/name: apisix
      ports: [{ protocol: TCP, port: 80 }]
    - from:
        - namespaceSelector:                 # 2) FSC Inway (system-to-system, §12)
            matchLabels:
              kubernetes.io/metadata.name: fsc
          podSelector:
            matchLabels:
              app.kubernetes.io/name: fsc-nlx-inway
      ports: [{ protocol: TCP, port: 80 }]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: fsc-inway-ingress
  namespace: fsc
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: fsc-nlx-inway
  policyTypes: [Ingress]
  ingress:
    - from: []                               # mTLS endpoint exposed via AGW; restrict at L3
      ports: [{ protocol: TCP, port: 8443 }]
      # Tighten further with ipBlock for the AGW subnet if the CNI supports it:
      # - from: [{ ipBlock: { cidr: 10.20.4.0/24 } }]
```

### 12.6 FSC-Core compliance checklist

| FSC-Core requirement | Where satisfied in this design |
|---|---|
| Outway→Inway mTLS with Trust Anchor X.509 | Inway terminates mTLS directly; AGW L4 passthrough never breaks the chain (§12.3) |
| Peer identity from certificate subject (OIN) | PKIoverheid private services certificate on the Inway/Manager (§12.4) |
| Authorization via Contracts / ServiceConnectionGrants | FSC-NLX Manager; token validated by Inway per request |
| `Fsc-Authorization` access token handling | FSC-NLX Inway (reference implementation) |
| Manager reachable via mTLS for contract negotiation | Dedicated L4 listener :9443 (§12.3) |
| Transaction logging | FSC-NLX txlog component; ship to the monitoring-logging stack |
| Directory listing of Peers/Services | Service registration with `internal: false` (§12.4) |
| Conformance evidence | Run the Logius **fsc-test-suite** (Manager/Inway/Outway + integration tests) against the ontw environment before joining the Group |

Items explicitly **out of FSC scope** and unaffected: the §1–§7 front-channel
path, the WAF policy, Let's Encrypt issuance, and the Key Vault sync.

### 12.7 Rollout additions

Append to the §10 plan:

9. Request PKIoverheid private services certificates (OIN of the serving
   organization) for Inway and Manager — **longest lead time; start first.**
10. Deploy FSC-NLX (Manager, Inway, txlog, controller) in the `fsc` namespace
    with the internal CA issuer for component-internal TLS.
11. Add the AGW L4 listeners/pools/rules (§12.3); verify TCP probe health.
12. Publish DNS for `fsc-inway`/`fsc-manager` hostnames; register the
    organization and the `open-zaak` service in the Group Directory.
13. Run the Logius fsc-test-suite; archive the results as compliance evidence.
14. Negotiate the first Contract with a peer and validate an end-to-end
    request: peer Outway → AGW :8443 → Inway → `openzaak-nginx`, confirming
    the transaction appears in both peers' transaction logs.

### 12.8 Troubleshooting additions

| Symptom | Likely cause | Check |
|---|---|---|
| Peer Outway gets TLS alert `certificate required` / handshake failure | AGW listener accidentally created as TLS (terminating) instead of TCP | Listener `protocol = "Tcp"`, no certificate attached (§12.3) |
| Inway logs `unknown certificate authority` | Outway cert not from the Group Trust Anchor, or TA bundle on the Inway outdated | TA configuration in FSC-NLX values; compare Group profile |
| Inway rejects with `invalid token` despite valid contract | Token bound to a different cert than presented (passthrough broken somewhere) | Confirm no TLS-inspecting device between AGW and Inway; token `cnf` vs presented cert |
| Manager unreachable for peers | L4 listener/port not exposed, or NSG blocks 9443 | AGW rule-fsc-manager health; NSG on the AGW subnet |
| Inway sees AGW subnet IPs only in logs | Proxy Protocol not enabled (or enabled on one side only) | Enable PPv1 on **both** AGW backend settings and the Inway listener, or accept gateway IPs |

---

*Document generated as a solution proposal; adjust resource names, CIDRs, and subscription identifiers to the target environment (ontw/test/acc/prod).*