List the Keycloak Identity-Provider instances configured on a given realm of an aks-blue cluster. Discovery helper — run this before `/kc-idp-secret` when the alias is unknown, since the same upstream Entra app is aliased differently per realm.

Usage: `/kc-list-idp <cluster> <realm>`

Examples:
- `/kc-list-idp aks-blue-ontw-info master`   → shows e.g. `alias=oidc-admin-info clientId=2e74f511-...`
- `/kc-list-idp aks-blue-ontw-info podiumd`  → shows e.g. `alias=oidc-info clientId=2e74f511-...` (same Entra app, different alias)

Cluster suffix maps to Azure: `ontw-<x>` → subscription `O-<Xxxx>` (e.g. `O-Info`), RG `rg-ontw-<x>`. Valid `<x>`: `dim1|dimp|icat|info|mayk`.

Behavior: write the script below to `tmp/kc-list-idp.run.sh` with `CTX`/`SUB`/`REALM` substituted from `$ARGUMENTS`, run it via PowerShell `wsl -d Ubuntu-24.04 -- bash /mnt/c/.../tmp/kc-list-idp.run.sh` (WSL required — direct Windows calls time out). For each IdP print `alias`, `providerId`, `enabled`, `config.clientId`. Read-only; no writes.

Same environment pins and admin-token flow as `/kc-idp-secret` (see that command for the rationale: `AZURE_CONFIG_DIR=$HOME/.azure-aks-blue`, operator client-credentials on the master realm, fallback `admin-cli`).

Reference script:

```bash
#!/usr/bin/env bash
set -uo pipefail
export PATH="$HOME/.local/bin:/home/john/bin:/usr/bin:/bin"
export AZURE_CONFIG_DIR="${AZURE_CONFIG_DIR:-$HOME/.azure-aks-blue}"
CTX=aks-blue-ontw-info; SUB=O-Info; NS=podiumd; PORT=28081
REALM="${1:-podiumd}"
az account set --subscription "$SUB" --only-show-errors >/dev/null 2>&1
kubectl --context "$CTX" -n "$NS" port-forward svc/keycloak-service $PORT:8080 >/tmp/pf.log 2>&1 &
PF=$!; trap "kill $PF 2>/dev/null||true" EXIT; sleep 6
OP_CID=$(kubectl --context "$CTX" -n "$NS" get secret keycloak-operator-client-secret -o jsonpath='{.data.clientId}'|base64 -d)
OP_SEC=$(kubectl --context "$CTX" -n "$NS" get secret keycloak-operator-client-secret -o jsonpath='{.data.client-secret}'|base64 -d)
TOKEN=$(curl -sS "http://localhost:$PORT/realms/master/protocol/openid-connect/token" \
  -d "client_id=$OP_CID&client_secret=$OP_SEC&grant_type=client_credentials" \
  | python3 -c "import sys,json;print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)
[ -z "$TOKEN" ] && { echo NO_TOKEN; exit 1; }
echo "=== IdP instances on realm=$REALM ==="
curl -fsS "http://localhost:$PORT/admin/realms/$REALM/identity-provider/instances" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json;[print(f\"alias={i.get('alias'):24s} providerId={i.get('providerId'):12s} enabled={i.get('enabled')} clientId={i.get('config',{}).get('clientId')}\") for i in json.load(sys.stdin)]"
```
