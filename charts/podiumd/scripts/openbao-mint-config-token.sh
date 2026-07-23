#!/usr/bin/env bash
#
# openbao-mint-config-token.sh — mint the scoped periodic token the
# openbao-config Job authenticates with, and seed it into the bootstrap Secret.
#
# Replaces parking the ROOT token in the cluster (least privilege). The script:
#   1. writes the `podiumd-config-job` policy into OpenBao — exactly the paths
#      charts/podiumd/templates/openbao-config-job.yaml touches, nothing more;
#   2. mints an ORPHAN PERIODIC token carrying that policy (orphan: survives
#      root-token revocation; periodic: the config Job renews it on every run,
#      so it never expires as long as you deploy within TOKEN_PERIOD);
#   3. seeds it into Secret/<BOOTSTRAP_SECRET> (key `token`) in the namespace;
#   4. verifies the new token works;
#   5. with --revoke-root, revokes the root token afterwards (recommended).
#
# Run from your own machine after the one-time `bao operator init` + unseal
# (component doc §5). Re-run any time to rotate the config token — e.g. when no
# deploy has renewed it within TOKEN_PERIOD and it has expired. If the root
# token was already revoked, generate a new one first with a quorum of unseal
# key shares: `bao operator generate-root`.
#
# Usage:
#   NAMESPACE=<ns> ./openbao-mint-config-token.sh [--revoke-root]
#
# Environment:
#   NAMESPACE         required — namespace of the OpenBao pods
#   RELEASE           helm release name                  (default: podiumd)
#   OPENBAO_POD       pod to exec the bao CLI in         (default: <RELEASE>-openbao-0)
#   BOOTSTRAP_SECRET  Secret to seed; must match openbao.configuration.bootstrapTokenSecret
#                                                        (default: openbao-bootstrap-token)
#   KV_PATH           kv-v2 mount path; must match openbao.configuration.kvPath
#                                                        (default: secret)
#   TOKEN_PERIOD      renewal period of the minted token (default: 768h = 32 days)
#   BAO_ROOT_TOKEN    root token (prompted silently if unset)
#
# Requires: bash 3+, kubectl (context pointing at the right cluster).

set -euo pipefail

usage() {
  sed -n '2,37p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}
[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && usage 0

REVOKE_ROOT=0
if [[ "${1:-}" == "--revoke-root" ]]; then
  REVOKE_ROOT=1
  shift
fi
[[ "$#" -eq 0 ]] || { echo "ERROR: unexpected argument '${1}'" >&2; usage 1; }

command -v kubectl >/dev/null 2>&1 || { echo "ERROR: kubectl not found" >&2; exit 1; }

NAMESPACE="${NAMESPACE:-}"
[[ -n "${NAMESPACE}" ]] || { echo "ERROR: NAMESPACE is not set" >&2; usage 1; }
RELEASE="${RELEASE:-podiumd}"
OPENBAO_POD="${OPENBAO_POD:-${RELEASE}-openbao-0}"
BOOTSTRAP_SECRET="${BOOTSTRAP_SECRET:-openbao-bootstrap-token}"
KV_PATH="${KV_PATH:-secret}"
TOKEN_PERIOD="${TOKEN_PERIOD:-768h}"
POLICY_NAME="podiumd-config-job"
# Writes are forwarded to the active node, so any unsealed pod works as the
# exec target; address the active Service explicitly anyway.
BAO_ADDR="http://${RELEASE}-openbao-active:8200"

if [[ -z "${BAO_ROOT_TOKEN:-}" ]]; then
  read -r -s -p "OpenBao root token: " BAO_ROOT_TOKEN
  echo >&2
fi
[[ -n "${BAO_ROOT_TOKEN}" ]] || { echo "ERROR: empty root token" >&2; exit 1; }

echo "Minting scoped config token via pod ${OPENBAO_POD} (namespace ${NAMESPACE})"

# The token is embedded in the script streamed over the exec channel (stdin),
# never in command arguments — it stays out of `ps`, shell history on the pod,
# and the K8s audit log (which records exec args, not the streamed input).
# The unquoted heredoc expands every ${...} locally before transmission.
NEW_TOKEN=$(kubectl exec -i -n "${NAMESPACE}" "${OPENBAO_POD}" -- sh -e <<EOS
export BAO_ADDR="${BAO_ADDR}"
export BAO_TOKEN="${BAO_ROOT_TOKEN}"

# Scoped policy for the openbao-config Job — see openbao-config-job.yaml for
# the operations behind each path. sudo on sys/mounts/<kv> and sys/auth/oidc:
# enabling a secrets engine / auth method requires sudo in addition to the
# path capabilities. identity read paths: group/alias lookups on re-runs.
bao policy write ${POLICY_NAME} - >&2 <<'HCL'
path "sys/mounts"                { capabilities = ["read"] }
path "sys/mounts/${KV_PATH}"     { capabilities = ["create", "read", "update", "sudo"] }
path "sys/policies/acl/uploader" { capabilities = ["create", "read", "update"] }
path "sys/auth"                  { capabilities = ["read"] }
path "sys/auth/oidc"             { capabilities = ["create", "update", "sudo"] }
path "auth/oidc/config"          { capabilities = ["create", "read", "update"] }
path "auth/oidc/role/uploader"   { capabilities = ["create", "read", "update"] }
path "identity/group"            { capabilities = ["create", "update"] }
path "identity/group/name/*"     { capabilities = ["read"] }
path "identity/group-alias"      { capabilities = ["create", "update"] }
path "identity/group-alias/id/*" { capabilities = ["read", "update"] }
HCL

# Orphan + periodic: survives root revocation, renewable forever within period.
# Default policy stays attached (lookup-self / renew-self for the config Job).
bao token create \
  -orphan \
  -policy=${POLICY_NAME} \
  -period=${TOKEN_PERIOD} \
  -display-name=${POLICY_NAME} \
  -field=token
EOS
)
[[ -n "${NEW_TOKEN}" ]] || { echo "ERROR: token create returned nothing" >&2; exit 1; }
echo "Policy '${POLICY_NAME}' written; orphan periodic token minted (period ${TOKEN_PERIOD})."

echo "Seeding Secret/${BOOTSTRAP_SECRET} (key: token)"
printf '%s' "${NEW_TOKEN}" | kubectl create secret generic "${BOOTSTRAP_SECRET}" \
  -n "${NAMESPACE}" --from-file=token=/dev/stdin \
  --dry-run=client -o yaml | kubectl apply -n "${NAMESPACE}" -f -

echo "Verifying the seeded token"
kubectl exec -i -n "${NAMESPACE}" "${OPENBAO_POD}" -- sh -e >&2 <<EOS
export BAO_ADDR="${BAO_ADDR}"
export BAO_TOKEN="${NEW_TOKEN}"
bao token lookup >/dev/null
echo "OK: config token is valid."
EOS

if [[ "${REVOKE_ROOT}" -eq 1 ]]; then
  echo
  echo "WARNING: about to revoke the OpenBao root token. This is irreversible."
  echo "Recovery afterwards requires a quorum of unseal key shares"
  echo "('bao operator generate-root') — unseal keys are NOT affected."
  read -r -p "Revoke the root token now? [y/N] " answer
  if [[ "${answer}" == "y" || "${answer}" == "Y" ]]; then
    kubectl exec -i -n "${NAMESPACE}" "${OPENBAO_POD}" -- sh -e >&2 <<EOS
export BAO_ADDR="${BAO_ADDR}"
export BAO_TOKEN="${BAO_ROOT_TOKEN}"
bao token revoke -self >/dev/null
echo "Root token revoked."
EOS
  else
    echo "Root token NOT revoked."
  fi
else
  echo
  echo "Root token left untouched. Recommended once a deploy has succeeded with"
  echo "the new token: re-run with --revoke-root (component doc §7)."
fi

echo
echo "Done. The openbao-config Job renews this token on every run; if no deploy"
echo "happens within ${TOKEN_PERIOD} the token expires — re-run this script to rotate."
