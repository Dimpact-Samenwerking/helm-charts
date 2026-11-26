# Upgrade guide: monitoring-logging 1.0.16 → 1.0.17

## Summary of changes

Drops the `offline_access` OAuth scope (and `use_refresh_token`) from Grafana's
Keycloak login config, and makes Grafana's own session-length settings
explicit.

## Why

The podiumd chart's `monitoring` Keycloak client stopped granting
`offline_access` (podiumd PR #441 / `docs/apps/keycloak/keycloak-security-updates.md`
§ "Offline Access Disabled"). Grafana was still requesting that scope and
setting `use_refresh_token: true` — Keycloak now silently drops the
unauthorized scope from the auth request, so `use_refresh_token` had nothing to
refresh with. No functional break (Grafana falls back to normal token
behavior), but sessions now expire on Grafana's own session-cookie settings
rather than being silently renewed via a persistent refresh token.

## Changes

- `grafana.grafana.ini.auth.generic_oauth.scopes`: drops `offline_access`
  (`openid email profile offline_access roles` → `openid email profile roles`).
- `grafana.grafana.ini.auth.generic_oauth.use_refresh_token`: `true` → `false`.
- `grafana.grafana.ini.auth.login_maximum_inactive_lifetime_duration` (new,
  `7d`) and `login_maximum_lifetime_duration` (new, `30d`) — Grafana's own
  upstream defaults, set explicitly so the session-length knob is visible. See
  `docs/grafana-auth.md` § "Session lifetime" for how to raise them.

## Action required

**None** unless an environment's operators are already relying on long-lived
Grafana sessions surviving well past 30 days without re-login — those
environments should set `login_maximum_lifetime_duration` (and
`login_maximum_inactive_lifetime_duration` if needed) explicitly in
`values-monitoring.yaml` after this upgrade. Everyone else sees no behavior
change: `offline_access` was already non-functional for this client before
this hop, since Keycloak was already rejecting/ignoring the scope for
`monitoring`.
