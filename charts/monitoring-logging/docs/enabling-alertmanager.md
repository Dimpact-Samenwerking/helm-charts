# Enabling AlertManager

AlertManager is disabled by default in the monitoring-logging chart. This document explains
how to enable it and integrate it with Grafana.

## Background

AlertManager is part of the `kube-prometheus-stack` dependency. When disabled, neither
the AlertManager deployment nor its Grafana datasource are provisioned. This is intentional
— alert routing requires environment-specific configuration (routes, receivers, inhibition
rules) that cannot have sensible defaults.

## What NOT to do

> **⚠️ Grafana 12.x compatibility warning**
>
> Do **not** set `datasources.alertmanager.enabled: false` in Grafana values. This generates
> a ConfigMap key named `alertmanager` containing only `enabled: false`, which gets mounted
> as a file in Grafana's datasource provisioning directory. Grafana's file-based provisioning
> parses it as a datasource config and fails with:
>
> ```
> Datasource provisioning error: data source not found
> ```
>
> This causes a crash loop in Grafana 12.x. Simply omit the `datasources.alertmanager` key
> entirely if AlertManager is disabled.

Similarly, do **not** add `deleteDatasources: [{name: Alertmanager}]` once the Alertmanager
datasource has already been deleted — Grafana 12.x with `feature_toggles.provisioning: true`
treats a missing-datasource delete as a fatal error rather than a warning.

## Steps to enable

### 1. Enable AlertManager in kube-prometheus-stack

```yaml
kube-prometheus-stack:
  alertmanager:
    enabled: true
    alertmanagerSpec:
      nodeSelector:
        kubernetes.azure.com/mode: user
      resources:
        requests:
          cpu: 10m
          memory: 64Mi
        limits:
          cpu: 100m
          memory: 128Mi
      storage:
        volumeClaimTemplate:
          spec:
            storageClassName: managed-csi
            accessModes: ["ReadWriteOnce"]
            resources:
              requests:
                storage: 1Gi
    config:
      global:
        resolve_timeout: 5m
      route:
        group_by: ["alertname", "namespace"]
        group_wait: 30s
        group_interval: 5m
        repeat_interval: 12h
        receiver: "null"
        routes: []   # Add your routes here
      receivers:
        - name: "null"
      inhibit_rules: []
```

### 2. Add the AlertManager datasource to Grafana

Add this under `grafana.datasources.datasources.yaml.datasources` in your values file:

```yaml
grafana:
  datasources:
    datasources.yaml:
      apiVersion: 1
      datasources:
        # ... your existing Prometheus and Loki entries ...
        - name: Alertmanager
          type: alertmanager
          uid: alertmanager
          access: proxy
          url: http://{{ .Release.Name }}-kube-prometheus-stack-alertmanager:9093
          editable: true
          readOnly: false
          jsonData:
            implementation: prometheus
```

### 3. Enable the AlertManager datasource in the Grafana sidecar

The sidecar section controls whether the Grafana chart's k8s-sidecar container
watches for datasource ConfigMaps. Do **not** set `sidecar.datasources.alertmanager`:
just leave the sidecar enabled:

```yaml
grafana:
  sidecar:
    datasources:
      enabled: true
```

### 4. Expose AlertManager via Ingress (optional)

```yaml
kube-prometheus-stack:
  alertmanager:
    ingress:
      enabled: true
      ingressClassName: nginx
      annotations:
        cert-manager.io/cluster-issuer: letsencrypt-prod
        nginx.ingress.kubernetes.io/ssl-redirect: "true"
      hosts:
        - alertmanager.your-env.example.nl
      tls:
        - secretName: alertmanager-tls
          hosts:
            - alertmanager.your-env.example.nl
```

### 5. Add the AlertManager image to your ACR override file (aks-blue environments)

The AlertManager image is managed by `kube-prometheus-stack`. Add an ACR override:

```yaml
kube-prometheus-stack:
  alertmanager:
    alertmanagerSpec:
      image:
        registry: <your-acr>.azurecr.io
        repository: prometheus/alertmanager
        # No tag override needed — chart default is used
```

The AlertManager image tag is defined in the chart's bundled `kube-prometheus-stack` values.
Check the current tag with:

```bash
helm show values prometheus-community/kube-prometheus-stack --version <chart-version> \
  | grep -A3 "alertmanager:" | grep "tag:"
```

## Grafana dashboards

When `kube-prometheus-stack.alertmanager.enabled: true`, the chart automatically provisions
an AlertManager dashboard in Grafana. No additional configuration is needed.

To force dashboard provisioning even when AlertManager is disabled (e.g. for a shared
dashboard namespace), set:

```yaml
kube-prometheus-stack:
  alertmanager:
    forceDeployDashboards: true
```

## Removing AlertManager after it was enabled

If you previously had AlertManager enabled and want to disable it:

1. Set `kube-prometheus-stack.alertmanager.enabled: false`
2. Remove the Alertmanager entry from `grafana.datasources.datasources.yaml.datasources`
3. **Do not** add `grafana.deleteDatasources: [{name: Alertmanager}]` — Grafana 12.x
   treats this as fatal if the datasource no longer exists. Instead, manually delete it
   via the Grafana UI or API if needed:
   ```bash
   curl -X DELETE http://admin:password@grafana/api/datasources/uid/alertmanager
   ```
4. Delete the AlertManager PVC if storage was configured:
   ```bash
   kubectl delete pvc -l app.kubernetes.io/name=alertmanager -n monitoring
   ```

## Grafana 12.x App Platform feature toggles

Grafana 12 introduced several experimental Kubernetes-native features under `feature_toggles`.
The following toggles are **not compatible** with standard file-based provisioning when
an existing SQLite database is present, and will cause a crash loop:

| Toggle | Effect | Status |
|--------|--------|--------|
| `provisioning` | API-based datasource provisioning via K8s API | ❌ Do not enable |
| `kubernetesDashboards` | K8s-API-based dashboard storage | ❌ Do not enable |
| `kubernetesClientDashboardsFolders` | K8s-API-based folder management | ❌ Do not enable |
| `grafanaAPIServerEnsureKubectlAccess` | kubectl access for K8s API integration | ❌ Do not enable |
| `grafanaAdvisor` | Advisor panel in Grafana UI (recommendations) | ✅ Safe to enable |

These features require a fresh Grafana install with no existing database, plus Grafana
having specific Kubernetes API RBAC. They are not suitable for the standard deployment pattern.
