# Upgrade guide: monitoring-logging 1.0.17 → 1.0.18

## Summary of changes

Routine image bumps carried in from the open Renovate stack (PRs #299, #318,
#376):

- `kube-prometheus-stack.prometheus-operator.admissionWebhooks.patch.image`
  (`jkroepke/kube-webhook-certgen`): `1.8.0` → `1.8.8`.
- `prometheus-pushgateway.image` (`quay.io/prometheus/pushgateway`):
  `v1.11.1` → `v1.11.3`.
- `alloy.image` (`docker.io/grafana/alloy`): `v1.14.0` → `v1.19.2`.

## Why

Renovate opened these as separate PRs; folded into this release branch per
the "one open monitoring-logging release branch + PR at a time" policy
instead of merging them independently.

## Action required

**None.** Patch/minor upstream bumps only, no config surface changed.
