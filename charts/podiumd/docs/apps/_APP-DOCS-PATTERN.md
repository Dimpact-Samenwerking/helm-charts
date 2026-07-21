# Per-app documentation pattern

How the `docs/apps/` tree is organised and what every app document must look
like. Follow this when adding a component to the chart or documenting an
existing one. (Folder-level layout of `docs/` itself: see
[`../_README.MD`](../_README.MD).)

## Layout rules

- One folder per component: `docs/apps/<app>/` — `<app>` matches the values
  key / template prefix in the chart (`openzaak`, `frankgateway`, `openbao`, …).
- Every folder has exactly one `<app>-BASICS.md` — the entry point. **A new
  chart component is not done until its BASICS file exists.**
- Deep dives (runbooks, tuning guides, known issues, design notes) are
  separate files in the same folder, linked from the BASICS "Related
  documents" section. Never inline them into the BASICS file.
- No app docs at the `docs/` root — everything app-specific lives under
  `docs/apps/<app>/`.
- Superseded components keep their folder; add a short banner at the top of
  each file pointing to the successor (see `apisix/` → `frankgateway/`).

## BASICS file skeleton (mandatory headings, this order)

```markdown
# <App display name> — Basics

## Management summary

## What it is

## Required resources

### Database

### Storage

### Routing / exposure (NGINX Gateway Fabric)

### Other dependencies

## CPU and memory

## Integrating <App> as a new app

## Related documents
```

Keep every heading even when a section is empty — write "None." with a
one-line reason (e.g. "Database: none — configuration lives in etcd"). That
tells the reader the question was considered, not forgotten.

## What goes in each section

| Section | Content |
|---|---|
| **Management summary** | Plain language, no jargon — what the component does for the municipality, why PodiumD includes it, what it needs to run, rough footprint. A non-technical reader must be able to stop after this section. |
| **What it is** | Upstream project + link, image repository and chart-pinned tag/digest (with the `values.yaml` key), how it is deployed (subchart vs own templates), enable flag if optional, and a bullet list of every runtime component (Deployments, StatefulSets, Jobs, sidecars) with replica counts and one-line purposes. |
| **Database** | Yes/no. If yes: the per-app Secret/ConfigMap credential contract (names + required keys), who creates it (chart vs environment deployment), server used. |
| **Storage** | Yes/no. If yes: PV/PVC names, size, access mode, storage class, Azure Files share name, what the data is, retention behaviour (`resource-policy: keep`?). |
| **Routing / exposure** | Public or ClusterIP-only. Hostname pattern, HTTPRoute name + Gateway, backend service — and state explicitly that routes are created deploy-side (ADO `ExternalsPodiumD`), not by this chart, when that is the case. |
| **Other dependencies** | Redis (with DB numbers — keep `redis/redis-ha-databases.md` in sync), Keycloak clients/realm config, inter-app secrets, external APIs, SMTP — with the values keys that configure each. |
| **CPU and memory** | Table: one row per container — CPU/mem request, CPU/mem limit ("not set (burstable)" when absent). Add observed usage (`kubectl top`, dated, per environment) when measured, and any sizing advice from `misc/resource-overview.md`. |
| **Integrating as a new app** | Numbered, actionable steps to bring the component up in a fresh environment: provision DB/storage, values to set (the per-environment must-sets), Keycloak clients, secrets, DNS + route, and a final verify step (what to check, which jobs must complete). |
| **Related documents** | Relative links to the other files in this folder, one line each on when to read them. |

## Style

- Reference chart facts precisely: values keys (`openzaak.image.tag`),
  template paths (`templates/frankgateway-config.yaml`), Secret/ConfigMap
  names — so drift is detectable by grep.
- Pin claims in time when they can drift: date observed-usage numbers,
  name the release a decision was taken in.
- English; `— Basics` title suffix; relative links within `docs/`.

## Reference examples

- [`openzaak/openzaak-BASICS.md`](openzaak/openzaak-BASICS.md) — full-featured
  app (DB + storage + public route + many dependencies).
- [`clamav/clamav-BASICS.md`](clamav/clamav-BASICS.md) — minimal internal
  component (mostly "None." sections).
