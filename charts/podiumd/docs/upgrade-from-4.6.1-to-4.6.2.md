# Upgrade guide: PodiumD 4.6.1 → 4.6.2

## Changes

### `redis-ha-label-master` kubectl image replaced

The `lachlanevenson/k8s-kubectl` image (unofficial Docker Hub maintainer, K8s 1.25 EOL) has been
replaced with `registry.k8s.io/kubectl:v1.33.0` — the official Kubernetes project image.

For **ACR-based environments**, update the repository override:

```yaml
redis-operator:
  redis-ha:
    labelMasterJob:
      image:
        repository: <acr>/kubectl
```

No tag override is needed — the tag is set by the chart default (`v1.33.0`).

For the full list of new and changed images in this release see
[docs/images/images-4.6.2.yaml](images/images-4.6.2.yaml).
