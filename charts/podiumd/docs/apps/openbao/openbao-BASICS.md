# OpenBao — Basics

> **Placeholder.** OpenBao is documented together with Frank!Gateway, the
> component it exists for in PodiumD. Everything that used to be here — what
> it is, database, route, certificate, Key Vault items, seal model, Keycloak,
> values, bootstrap runbook, sizing — is in
> [`../frankgateway/frankgateway-openbao.md`](../frankgateway/frankgateway-openbao.md).

## Management summary

OpenBao is the secrets vault of PodiumD. Frank!Gateway reads the keys for the
external services it calls from it, so enabling Frank!Gateway requires
OpenBao. Read the
[management summary in the Frank!Gateway docs](../frankgateway/frankgateway-openbao.md#management-summary).

## Where to find what

| Topic | Section |
|---|---|
| DevOps checklist per environment | [DevOps TL;DR](../frankgateway/frankgateway-openbao.md#devops-tldr) |
| Database, route, TLS, Key Vault, seal model, Keycloak | [§3 Requirements](../frankgateway/frankgateway-openbao.md#3-requirements) |
| Values to set | [§4 Values reference](../frankgateway/frankgateway-openbao.md#4-values-reference) |
| First install, and unsealing after every restart | [Deployment runbook](../frankgateway/frankgateway-deploy-runbook.md) |
| CPU and memory | [§8 Sizing](../frankgateway/frankgateway-openbao.md#8-sizing-defaults) |

## Related documents

- [`../frankgateway/frankgateway-openbao.md`](../frankgateway/frankgateway-openbao.md)
  — the full OpenBao document.
- [`../frankgateway/frankgateway-BASICS.md`](../frankgateway/frankgateway-BASICS.md)
  — Frank!Gateway, the component OpenBao serves.
