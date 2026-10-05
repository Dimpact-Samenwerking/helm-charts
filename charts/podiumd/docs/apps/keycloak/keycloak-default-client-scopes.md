# Keycloak default client scopes for `zac` and `ita`

ZAC and ITA read the user's roles from the access token. Keycloak only puts
roles in the token when the client has the `roles` client scope as a
**default** scope.

Since 4.10.0 the realm config sets `defaultClientScopes` on every client
(`*defaultDefaultClientScopes`, plus `service_account` for service-account
clients). Before that, from 4.9.1 on, it set only `optionalClientScopes`.
Keycloak treats a client's default and optional scopes as one complete set as
soon as either list is given, so every client the realm import created got
**no** default scopes at all. Clients that already existed before 4.9.1 kept
theirs, because keycloak-config-cli leaves a client's default scopes alone
when the config does not list them. That is why the older ontw environments
worked and a rebuilt realm such as johnb00's did not.

Deploying 4.10.0 adds the missing scopes to existing clients. This page
describes how to check a realm, and how to add the scopes by hand on an
environment that still runs an older release.

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

Service-account clients (`zac-admin-client`, `pabc-keycloak-admin`,
`monitoring`, `datamigratie`) also keep `service_account`.

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

On 4.10.0 or later: deploy. The realm import adds the missing default scopes
to every client in the realm config. The steps below are for an environment
that still runs an older release.

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

On a release before 4.10.0 the realm import does not remove these again:
keycloak-config-cli only changes an existing client's default scopes when the
realm config lists them, and before 4.10.0 it does not. A client the realm
import creates on such a release still gets no default scopes; repeat the
steps for it.

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
