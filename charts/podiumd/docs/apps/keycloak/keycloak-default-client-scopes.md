# Keycloak default client scopes for `zac` and `ita`

ZAC and ITA read the user's roles from the access token. Keycloak only puts
roles in the token when the client has the `roles` client scope as a
**default** scope. The chart does not set `defaultClientScopes` on these
clients: it relies on Keycloak assigning the realm's default scopes when the
realm import creates a client.

On every existing ontw environment that works. On a realm that was created
from scratch it did not: after johnb00's cluster was rebuilt, the clients from
the realm config had no default client scopes at all (see helm-charts PR #480).
This page describes how to check a realm and how to add the scopes.

## Symptoms

- ZAC logs `functional roles: '[]'` for a user who is in a PABC group such as
  `administrators`, and the user gets a 403 / "u heeft geen toestemming om
  deze pagina te bekijken".
- ITA shows the user no rights, although the user has the right `ita` client
  roles.
- The access token has no `realm_access` and no `resource_access` claim.

## What the clients need

The realm's default set, as on the working ontw environments:

| Scope | Why |
| --- | --- |
| `roles` | Mappers `realm roles` (`realm_access.roles`, the functional roles ZAC sends to PABC), `client roles` (`resource_access.<client>.roles`), `zac roles` (`roles`) and `audience resolve`. The chart defines this scope in the realm config. |
| `basic` | The `sub` claim (Keycloak 25+). |
| `profile`, `email` | `preferred_username`, name and email claims. |
| `web-origins` | Allowed CORS origins for the browser login. |
| `acr` | The `acr` claim. |

`address`, `phone` and `microprofile-jwt` stay **optional** scopes; the realm
config sets those on every client. `offline_access` is disabled realm-wide on
purpose (see [keycloak-security-updates.md](keycloak-security-updates.md)).

## 1. Check the realm

With the Admin Console: **podiumd** realm → **Clients** → `zac` →
**Client scopes** tab. The **Assigned type** of `roles`, `basic`, `profile`,
`email`, `web-origins` and `acr` must be **Default**. Repeat for `ita`.

With `kcadm.sh`, which is in the Keycloak image:

```bash
kc() { /opt/keycloak/bin/kcadm.sh "$@" --config /tmp/kcadm.config; }
kc config credentials --server http://localhost:8080 --realm master \
  --client keycloak-operator --secret "$KEYCLOAK_OPERATOR_SECRET"

for c in zac ita; do
  id=$(kc get clients -r podiumd -q clientId=$c --fields id --format csv --noquotes)
  echo "== $c"; kc get clients/$id/default-client-scopes -r podiumd --fields name --format csv --noquotes
done

# Realm defaults that new clients get:
kc get realms/podiumd/default-default-client-scopes --fields name --format csv --noquotes
```

The operator service-account secret is in the `keycloak-operator-client-secret`
Secret (key `client-secret`), the same credentials the realm import and
`pabc-keycloak-groups-job` use.

## 2. Add the missing scopes

With the Admin Console: **Clients** → `zac` → **Client scopes** →
**Add client scope** → select the missing scopes → **Add** → **Default**.
Repeat for `ita`.

With `kcadm.sh`:

```bash
for c in zac ita; do
  id=$(kc get clients -r podiumd -q clientId=$c --fields id --format csv --noquotes)
  for s in roles basic profile email web-origins acr; do
    sid=$(kc get client-scopes -r podiumd --fields id,name --format csv --noquotes | awk -F, -v s="$s" '$2==s{print $1}')
    [ -n "$sid" ] || { echo "client scope $s does not exist in realm podiumd"; continue; }
    kc update clients/$id/default-client-scopes/$sid -r podiumd && echo "$c: default scope $s"
  done
done
```

Adding a scope that is already assigned is a no-op. If a built-in scope such as
`basic` does not exist in the realm at all, the realm was created without
Keycloak's built-in scopes. Create it in the Admin Console
(**Client scopes** → **Create client scope**) or restore it from a realm that
has it, before assigning it.

Make the same scopes the realm defaults as well, so clients the realm import
creates later get them too:

```bash
for s in roles basic profile email web-origins acr; do
  sid=$(kc get client-scopes -r podiumd --fields id,name --format csv --noquotes | awk -F, -v s="$s" '$2==s{print $1}')
  [ -n "$sid" ] && kc update realms/podiumd/default-default-client-scopes/$sid
done
```

The realm import (keycloak-config-cli) does not remove these again: the realm
config sets `optionalClientScopes` on the clients, but not
`defaultClientScopes`, so it does not manage the default scopes.

**aks-blue environments:** a change with `kcadm.sh` through `kubectl exec` is a
manual change to the realm, outside the pipeline. Let a Keycloak administrator
do it in the Admin Console, and record it in the environment's change log.

## 3. Verify

In the Admin Console: **Clients** → `zac` → **Client scopes** → **Evaluate** →
pick a user who is in the `administrators` group → **Generated access token**.
The token must contain:

- `realm_access.roles` with `administrators` (the functional role ZAC sends to
  PABC),
- `resource_access.zac.roles` with the ZAC client roles of that group,
- `group_membership` and `preferred_username`.

For `ita`, `resource_access.ita.roles` and `roles` must hold the user's `ita`
client roles.

With `kcadm.sh`:

```bash
uid=$(kc get users -r podiumd -q username=<user> --fields id --format csv --noquotes)
id=$(kc get clients -r podiumd -q clientId=zac --fields id --format csv --noquotes)
kc get "clients/$id/evaluate-scopes/generate-example-access-token" -r podiumd \
  -q scope=openid -q userId=$uid | jq '{realm_access, resource_access, group_membership}'
```

Then log in to ZAC as that user. The ZAC log shows
`functional roles: [..., administrators, ...]`, and the dashboard loads.
