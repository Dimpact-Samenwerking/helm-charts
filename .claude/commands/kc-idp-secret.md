Verify or set a Keycloak Identity-Provider `clientSecret` on an aks-blue cluster, with authoritative DB confirmation. The Keycloak admin API masks `clientSecret` as `**********` on read, so the only proof of the stored value is a SHA-256 of the row in the Keycloak database.

Usage: `/kc-idp-secret <cluster> <realm> <alias> verify <value>`
       `/kc-idp-secret <cluster> <realm> <alias> set <value>`

- `<cluster>`: aks-blue context, e.g. `aks-blue-ontw-info` (subscription/RG derived: `ontw-info` → sub `O-Info`, RG `rg-ontw-info`; same pattern for `dim1|dimp|icat|info|mayk`).
- `<realm>`: Keycloak realm, e.g. `master` or `podiumd`.
- `<alias>`: IdP instance alias. NOTE the alias differs per realm for the same upstream Entra app — on ontw-info the "info admin" Entra app `2e74f511-6741-4e70-93c7-465cdd6b87a9` is `oidc-admin-info` on the `master` realm but `oidc-info` on the `podiumd` realm. Run `/kc-list-idp <cluster> <realm>` first if unsure.
- `verify`: read-only; PUT is skipped, only the DB SHA-256 is compared.
- `set`: GET the instance, replace ONLY `config.clientSecret`, PUT it back (all other config preserved), then DB-verify the write landed.

Examples:
- `/kc-idp-secret aks-blue-ontw-info master oidc-admin-info set oEr8Q~...`
- `/kc-idp-secret aks-blue-ontw-info podiumd oidc-info verify oEr8Q~...`

Important context / gotchas (learned the hard way):
- This IdP is **not** chart-provisioned. `keycloak.config.realmIdentityProviders` is intentionally empty in `values.yaml` (comment around line 139 — leaving it set would clobber per-gemeente Entra IdPs). The IdP and its secret live only inside Keycloak, set out-of-band. There is no Kubernetes Secret holding it (all 26 secrets in the `podiumd` namespace were scanned — none contain it).
- Run from **WSL**, not Windows directly: Windows Python/curl to registries and some endpoints time out; WSL works. Invoke via PowerShell `wsl -d Ubuntu-24.04 -- bash /mnt/c/.../tmp/<script>.sh` to avoid Git-Bash MSYS path mangling.
- Pin `AZURE_CONFIG_DIR=$HOME/.azure-aks-blue` (dedicated SSC-Hosting token cache, separate from the default Dimpact session) and `PATH=$HOME/.local/bin:/home/john/bin:...` (helm/kubelogin/az live there).
- Admin token: client-credentials with the `keycloak-operator-client-secret` Secret against the **master** realm (a master-realm admin token manages all realms cross-realm). Fallback: `admin-cli` password grant with the `keycloak-podiumd-admin` Secret.
- DB verify is mandatory after a `set` (API masks the value). Connect from an app pod that ships `psycopg` (objecttypen, else objecten). DB host from `keycloak-0` env `KC_DB_URL_HOST`, password from the `keycloak-secrets` Secret (`database_password`), `dbname=keycloak user=keycloak sslmode=require`. Scope the query by realm name (`identity_provider` spans realms; the same alias can exist in two realms).
- Never echo the raw secret in output — compare `sha256(value)[:16]` only.
- `set` is a mutating write on shared infra: only proceed when the user explicitly authorized this specific cluster + realm + alias + value.

Behavior: parse `$ARGUMENTS`, derive sub/RG from the cluster suffix, write the script below to `tmp/kc-idp-secret.run.sh` substituting the parsed values, then run it via WSL. Report: token OK, GET clientId/enabled, PUT http (204/200 expected) for `set`, and the final `realm=… alias=… db_sha16=… expected=… MATCH|MISMATCH` line.

Reference script (parameterize the UPPERCASE vars from `$ARGUMENTS`; for `verify` mode delete the `=== PUT ===` block):

```bash
#!/usr/bin/env bash
set -uo pipefail
export PATH="$HOME/.local/bin:/home/john/bin:/usr/bin:/bin"
export AZURE_CONFIG_DIR="${AZURE_CONFIG_DIR:-$HOME/.azure-aks-blue}"
CTX=aks-blue-ontw-info; SUB=O-Info; RG=rg-ontw-info; NS=podiumd
REALM=master; ALIAS=oidc-admin-info; PORT=28081
NEW_SECRET='REPLACE_ME'
EXP_SHA=$(printf %s "$NEW_SECRET" | sha256sum | cut -c1-16)
echo "target ctx=$CTX realm=$REALM alias=$ALIAS expected_sha16=$EXP_SHA"
az account set --subscription "$SUB" --only-show-errors 2>&1
if ! kubectl --context "$CTX" config view --minify >/dev/null 2>&1; then
  az aks get-credentials --subscription "$SUB" --resource-group "$RG" --name "$CTX" \
    --overwrite-existing --only-show-errors 2>&1 || { echo CRED-FAIL; exit 1; }
  kubelogin convert-kubeconfig -l azurecli >/dev/null 2>&1 || true
fi
kubectl --context "$CTX" -n "$NS" port-forward svc/keycloak-service $PORT:8080 >/tmp/pf.log 2>&1 &
PF=$!; trap "kill $PF 2>/dev/null||true" EXIT; sleep 6
OP_CID=$(kubectl --context "$CTX" -n "$NS" get secret keycloak-operator-client-secret -o jsonpath='{.data.clientId}'|base64 -d)
OP_SEC=$(kubectl --context "$CTX" -n "$NS" get secret keycloak-operator-client-secret -o jsonpath='{.data.client-secret}'|base64 -d)
TOKEN=$(curl -sS "http://localhost:$PORT/realms/master/protocol/openid-connect/token" \
  -d "client_id=$OP_CID&client_secret=$OP_SEC&grant_type=client_credentials" \
  | python3 -c "import sys,json;print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)
if [ -z "$TOKEN" ]; then
  AP=$(kubectl --context "$CTX" -n "$NS" get secret keycloak-podiumd-admin -o jsonpath='{.data.password}'|base64 -d)
  TOKEN=$(curl -sS "http://localhost:$PORT/realms/master/protocol/openid-connect/token" \
    -d "client_id=admin-cli&grant_type=password&username=admin&password=$AP" \
    | python3 -c "import sys,json;print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)
fi
[ -z "$TOKEN" ] && { echo NO_TOKEN; exit 1; }
CONF=$(curl -fsS "http://localhost:$PORT/admin/realms/$REALM/identity-provider/instances/$ALIAS" \
  -H "Authorization: Bearer $TOKEN") || { echo "GET FAILED (wrong alias for this realm? run /kc-list-idp)"; exit 1; }
echo "$CONF" | python3 -c "import sys,json;d=json.load(sys.stdin);print('clientId:',d['config'].get('clientId'),'enabled:',d.get('enabled'))"
# === PUT === (omit this whole block for verify mode)
NEW_CONF=$(echo "$CONF" | NEW="$NEW_SECRET" python3 -c "import sys,json,os;d=json.load(sys.stdin);d['config']['clientSecret']=os.environ['NEW'];print(json.dumps(d))")
HTTP=$(curl -sS -o /tmp/put.txt -w "%{http_code}" -X PUT \
  "http://localhost:$PORT/admin/realms/$REALM/identity-provider/instances/$ALIAS" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "$NEW_CONF")
echo "PUT http=$HTTP"; { [ "$HTTP" = 204 ] || [ "$HTTP" = 200 ]; } || { head -c 300 /tmp/put.txt; exit 1; }
# === DB verify (authoritative) ===
POD=$(kubectl --context "$CTX" -n "$NS" get pods -l app.kubernetes.io/name=objecttypen -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
[ -z "$POD" ] && POD=$(kubectl --context "$CTX" -n "$NS" get pods -l app.kubernetes.io/name=objecten -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
DBH=$(kubectl --context "$CTX" -n "$NS" exec keycloak-0 -- env 2>/dev/null | grep KC_DB_URL_HOST | cut -d= -f2 | tr -d '\r')
DBP=$(kubectl --context "$CTX" -n "$NS" get secret keycloak-secrets -o jsonpath='{.data.database_password}'|base64 -d)
kubectl --context "$CTX" -n "$NS" exec "$POD" -- env EXP="$EXP_SHA" DBH="$DBH" DBP="$DBP" ALIAS="$ALIAS" REALM="$REALM" python3 -c "
import os,hashlib,psycopg
c=psycopg.connect(host=os.environ['DBH'],dbname='keycloak',user='keycloak',password=os.environ['DBP'],sslmode='require')
cur=c.cursor()
cur.execute(\"\"\"SELECT r.name,ip.provider_alias,ipc.value FROM identity_provider ip
 JOIN realm r ON r.id=ip.realm_id
 JOIN identity_provider_config ipc ON ipc.identity_provider_id=ip.internal_id
 WHERE r.name=%s AND ip.provider_alias=%s AND ipc.name='clientSecret'\"\"\",(os.environ['REALM'],os.environ['ALIAS']))
exp=os.environ['EXP']
for rn,a,v in cur.fetchall() or [('','','')]:
    s=hashlib.sha256(v.encode()).hexdigest()[:16] if v else 'NOROW'
    print(f'realm={rn} {a}: db_sha16={s} expected={exp} -> {\"MATCH\" if s==exp else \"MISMATCH\"}')
c.close()"
```

Note: the upstream Entra app registration must hold the same secret value for SSO login to actually work — this command only sets the Keycloak side.
