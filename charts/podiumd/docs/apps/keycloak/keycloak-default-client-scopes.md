# Keycloak default client scopes for `zac` and `ita`

ZAC and ITA read the user's roles from the access token. Keycloak only puts
roles in the token when the client has the `roles` client scope as a
**default** scope.

From 4.9.1 to 4.9.4 the realm config set `optionalClientScopes` on every
client. Keycloak treats a client's default and optional scopes as one complete
set as soon as either list is given, so every client the realm import
**created** on those releases got no default scopes at all. Clients that
already existed kept theirs, which is why the older ontw environments worked
and a rebuilt realm such as johnb00's did not.

Since 4.10.0 client entries list no scopes, as before 4.9.1: a client the
import creates gets the realm's default scopes, and keycloak-config-cli leaves
the scopes of existing clients alone. Environments and Keycloak updates add
scopes to clients (for example `bsn` and `eherkenning` for DigiD/eHerkenning),
and the import no longer removes them. The `keycloak-repair-client-scopes`
Job (every deploy, `keycloak-operator.jobs.repairClientScopes.enabled`) repairs
what 4.9.1–4.9.4 left behind: a client with no default scopes, or only
`service_account`, gets the realm's default openid-connect scopes, and
`offline_access` is removed from every client. It never removes another scope.
The steps below are for an environment that runs the Job disabled or an
older release.

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

`address`, `phone` and `microprofile-jwt` are the realm's default **optional**
scopes. `offline_access` is disabled realm-wide on
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

# Every client without the roles scope (created by a 4.9.1–4.9.4 import):
for row in $(kc get clients -r podiumd --fields id,clientId --format csv --noquotes); do
  kc get "clients/${row%%,*}/default-client-scopes" -r podiumd --fields name --format csv --noquotes \
    | grep -qx roles || echo "no default scopes: ${row#*,}"
done
```

The operator service-account secret is in the `keycloak-operator-client-secret`
Secret (key `client-secret`), the same credentials the realm import and
`pabc-keycloak-groups-job` use.

## 2. Add the missing scopes

Since 4.10.0 the `keycloak-repair-client-scopes` Job adds them on every deploy.
Without it, add them by hand to every client the check above lists.

With the Admin Console: **Clients** → `<client>` → **Client scopes** →
**Add client scope** → select the missing scopes → **Add** → **Default**.

With `kcadm.sh`:

```bash
for c in zac ita; do   # the clients the check listed
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

The realm import does not remove them again: since 4.10.0 the realm config
lists no scopes on clients. On 4.9.1–4.9.4 a client the realm import creates
still gets no default scopes; repeat the steps for it.

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
