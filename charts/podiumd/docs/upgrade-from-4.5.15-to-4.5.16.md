# Upgrade guide: PodiumD 4.5.15 → 4.5.16

## Changes

### PABC bijgewerkt naar 1.1.0

De PABC sub-chart is bijgewerkt van 1.0.0 naar 1.1.0. De applicatie- en migratie-images zijn bijgewerkt naar versie `1.1.0`.

#### ACR image overrides

Voor **ACR-gebaseerde omgevingen** moeten de repository-overrides worden bijgewerkt:

```yaml
pabc:
  image:
    repository: <acr>/pabc-api
  migrations:
    image:
      repository: <acr>/pabc-migrations
  initContainers:
    waitFor:
      image:
        repository: <acr>/k8s-wait-for
```

Er zijn geen tag-overrides nodig — de tags worden bepaald door de chart-standaarden (`1.1.0` en `v2.0`).

#### NodeSelector voor AKS-omgevingen

Voor omgevingen die een node selector vereisen (bijv. AKS-blue met `kubernetes.azure.com/mode: user`),
moet de nodeSelector worden ingesteld op zowel de deployment als de migration job:

```yaml
pabc:
  nodeSelector:
    kubernetes.azure.com/mode: user
  migrations:
    nodeSelector:
      kubernetes.azure.com/mode: user
```

---

### Keycloak bijgewerkt naar 26.5.7

De Keycloak- en Keycloak Operator-images zijn bijgewerkt van `26.5.6` naar `26.5.7`.

Voor **ACR-gebaseerde omgevingen** die de Keycloak-image overschrijven:

```yaml
keycloak:
  image:
    repository: <acr>/keycloak

keycloak-operator:
  operator:
    image:
      repository: <acr>/keycloak-operator
```

Er zijn geen tag-overrides nodig — de tags worden bepaald door de chart-standaarden (`26.5.7`).

---

Voor de volledige lijst van nieuwe en gewijzigde images in deze release, zie
[docs/images/images-4.5.16.yaml](images/images-4.5.16.yaml).
