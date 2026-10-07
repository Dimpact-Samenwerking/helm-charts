#!/usr/bin/env bash
#
# openbao-activate.sh — make the in-chart OpenBao operational after a deploy,
# in one run: check, initialise, unseal, mint the tokens, configure, verify.
#
# Run it after the `helm upgrade` that deployed OpenBao, from a pipeline step
# or an operator machine. It is idempotent: on an operational vault it only
# checks, so it can run after every deploy.
#
# What one run does:
#   1. Preflight (read-only, stops on the first problem): cluster, release,
#      OpenBao pods, seal type, Key Vault item, Keycloak client secret.
#   2. Initialise, when the vault is not initialised yet. The one key OpenBao
#      returns (the recovery key with the static seal, the unseal key with
#      Shamir) goes to Key Vault item KEYVAULT_ITEM and is read back. This is
#      the ONLY Key Vault write the script does.
#   3. Unseal. Static seal: wait for every pod, restarting a pod that stays
#      sealed. Shamir: unseal every pod with the key.
#   4. Mint the scoped config token (scripts/openbao-mint-config-token.sh) and,
#      when Frank!Gateway is deployed, the gateway's read-only token, each into
#      its Kubernetes Secret. Only when a token is missing or invalid, or when
#      asked to rotate it.
#   5. Re-run the openbao-config Job from the deployed release
#      (`helm get hooks`), so the Keycloak login, the kv mount and the uploader
#      policy are configured without a second deploy.
#   6. Revoke the root token. The root token is never stored: the script uses
#      the one `bao operator init` returns, or creates a temporary one from the
#      key in Key Vault (`bao operator generate-root`) when it has to mint a
#      token on an already initialised vault.
#   7. Verify. Both tokens are periodic (32 days); CronJob
#      openbao-token-renewal renews them weekly, so they don't wait on a deploy.
#
# Usage:
#   KUBE_CONTEXT=<ctx> NAMESPACE=<ns> KEYVAULT=<kv> ./openbao-activate.sh [OPTIONS]
#
# Options:
#   --check                  Preflight and status only; changes nothing.
#                            Exits 1 when not operational (sealed, token invalid).
#   --rotate-config-token    Mint a new config token even if the current one works.
#   --rotate-reader-token    Mint a new gateway token even if the current one works.
#   --no-reader-token        Don't mint the gateway token (no Frank!Gateway, or
#                            the token is supplied another way).
#   --allow-shamir           Accept the Shamir seal. Without it the script stops
#                            when openbao.seal.static.key is not set, because
#                            Shamir pods stay sealed after every restart.
#   -h, --help               Show this help.
#
# Environment:
#   KUBE_CONTEXT        required — kube-context; passed to every kubectl and helm call
#   NAMESPACE           required — namespace of the PodiumD release
#   KEYVAULT            required — Azure Key Vault holding KEYVAULT_ITEM
#   AZ_SUBSCRIPTION     subscription of KEYVAULT     (default: the az CLI default)
#   KEYVAULT_ITEM       Key Vault item for the key   (default: openbao-unseal-key)
#   RELEASE             Helm release name            (default: podiumd)
#   KV_PATH             openbao.configuration.kvPath (default: secret)
#   READER_MOUNT        frankgateway.openbao.mount   (default: KV_PATH)
#   READER_SECRET       frankgateway.openbao.tokenSecret (default: frankgateway-openbao-token)
#   READER_PERIOD       renewal period of the gateway token (default: 768h = 32 days)
#   BOOTSTRAP_SECRET    openbao.configuration.bootstrapTokenSecret
#                                                    (default: openbao-bootstrap-token)
#   TOKEN_PERIOD        renewal period of the config token (default: 768h = 32 days)
#
# Key Vault item KEYVAULT_ITEM must exist before the first run, holding the
# placeholder value `pending-init` (create it with the other items from the
# pipeline). The script refuses to overwrite any other value.
#
# Requires: bash 4+, kubectl, helm 3+, az, jq. Exit code 0 means operational.

set -euo pipefail

usage() {
  sed -n '2,67p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

CHECK_ONLY=0
ROTATE_CONFIG=0
ROTATE_READER=0
NO_READER=0
ALLOW_SHAMIR=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --check)               CHECK_ONLY=1 ;;
    --rotate-config-token) ROTATE_CONFIG=1 ;;
    --rotate-reader-token) ROTATE_READER=1 ;;
    --no-reader-token)     NO_READER=1 ;;
    --allow-shamir)        ALLOW_SHAMIR=1 ;;
    -h|--help)             usage 0 ;;
    *) echo "ERROR: unknown argument '$1'" >&2; usage 1 ;;
  esac
  shift
done

for cmd in kubectl helm az jq; do
  command -v "${cmd}" >/dev/null 2>&1 || { echo "ERROR: ${cmd} not found" >&2; exit 1; }
done

KUBE_CONTEXT="${KUBE_CONTEXT:-}"
NAMESPACE="${NAMESPACE:-}"
KEYVAULT="${KEYVAULT:-}"
[[ -n "${KUBE_CONTEXT}" ]] || { echo "ERROR: KUBE_CONTEXT is not set" >&2; exit 1; }
[[ -n "${NAMESPACE}" ]] || { echo "ERROR: NAMESPACE is not set" >&2; exit 1; }
[[ -n "${KEYVAULT}" ]] || { echo "ERROR: KEYVAULT is not set" >&2; exit 1; }
KEYVAULT_ITEM="${KEYVAULT_ITEM:-openbao-unseal-key}"
RELEASE="${RELEASE:-podiumd}"
KV_PATH="${KV_PATH:-secret}"
READER_MOUNT="${READER_MOUNT:-${KV_PATH}}"
READER_SECRET="${READER_SECRET:-frankgateway-openbao-token}"
READER_PERIOD="${READER_PERIOD:-768h}"
BOOTSTRAP_SECRET="${BOOTSTRAP_SECRET:-openbao-bootstrap-token}"
TOKEN_PERIOD="${TOKEN_PERIOD:-768h}"
PLACEHOLDER="pending-init"
STS="${RELEASE}-openbao"
BAO_ADDR="http://${RELEASE}-openbao-active:8200"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

AZ_SUB=()
[[ -n "${AZ_SUBSCRIPTION:-}" ]] && AZ_SUB=(--subscription "${AZ_SUBSCRIPTION}")

# Every kubectl and helm call names the cluster and namespace.
kc() { kubectl --context "${KUBE_CONTEXT}" -n "${NAMESPACE}" "$@"; }
hc() { helm --kube-context "${KUBE_CONTEXT}" -n "${NAMESPACE}" "$@"; }

step() { echo; echo "==> $*"; }
ok()   { echo "    OK    $*"; }
info() { echo "    ..    $*"; }
fail() { echo "    FAIL  $*" >&2; exit 1; }

# Secrets and tokens travel inside the script streamed over stdin, never as
# command arguments: they stay out of `ps`, the pod's shell history and the
# Kubernetes audit log (which records exec arguments, not the streamed input).
bao_sh() { kc exec -i "$1" -c openbao -- sh -e; }

pod_status() {
  # `bao status` exits 2 when sealed; the JSON is what counts.
  kc exec "$1" -c openbao -- bao status -format=json 2>/dev/null || true
}

kv_get() {
  az keyvault secret show "${AZ_SUB[@]}" --vault-name "${KEYVAULT}" --name "${KEYVAULT_ITEM}" \
    --query value -o tsv 2>/dev/null
}

secret_value() {
  kc get secret "$1" -o jsonpath='{.data.token}' 2>/dev/null | base64 -d 2>/dev/null || true
}

token_lookup() {
  # Prints the lookup JSON for token $2 (via pod $1), or nothing when invalid.
  bao_sh "$1" <<EOS 2>/dev/null || true
export BAO_ADDR="${BAO_ADDR}" BAO_TOKEN="$2"
bao token lookup -format=json
EOS
}

###############################################################################
step "1. Preflight (read-only)"
###############################################################################
kc get namespace "${NAMESPACE}" >/dev/null 2>&1 \
  || kc get pods --field-selector=status.phase=Running -o name >/dev/null \
  || fail "cannot reach namespace ${NAMESPACE} on context ${KUBE_CONTEXT}"
ok "cluster reachable (context ${KUBE_CONTEXT}, namespace ${NAMESPACE})"

hc status "${RELEASE}" >/dev/null 2>&1 || fail "Helm release ${RELEASE} not found"
hc get hooks "${RELEASE}" | grep -q 'name: openbao-config' \
  || fail "release ${RELEASE} has no openbao-config Job: set openbao.enabled=true and openbao.configuration.enabled=true, and deploy"
ok "release ${RELEASE} deploys OpenBao and the openbao-config Job"

REPLICAS=$(kc get statefulset "${STS}" -o jsonpath='{.spec.replicas}' 2>/dev/null || true)
[[ -n "${REPLICAS}" ]] || fail "StatefulSet ${STS} not found"
for i in $(seq 0 $((REPLICAS - 1))); do
  phase=$(kc get pod "${STS}-${i}" -o jsonpath='{.status.phase}' 2>/dev/null || true)
  [[ "${phase}" == "Running" ]] || fail "pod ${STS}-${i} is '${phase:-missing}', not Running"
done
ok "${REPLICAS} OpenBao pods running"

STATUS=$(pod_status "${STS}-0")
[[ -n "${STATUS}" ]] || fail "bao status returned nothing on ${STS}-0"
SEAL_TYPE=$(jq -r .type <<<"${STATUS}")
INITIALIZED=$(jq -r .initialized <<<"${STATUS}")
if [[ "$(jq -r '.migration // false' <<<"${STATUS}")" == "true" ]]; then
  fail "${STS}-0 is in seal-migration mode (Shamir to static); finish the migration by hand (frankgateway-openbao.md §3.6.1)"
fi
case "${SEAL_TYPE}" in
  static) ok "static seal: the pods unseal themselves" ;;
  shamir)
    [[ "${ALLOW_SHAMIR}" -eq 1 ]] \
      || fail "Shamir seal: openbao.seal.static.key is not set. Set it (preferred) and deploy, or pass --allow-shamir"
    info "Shamir seal: every pod restart needs this script (or a manual unseal) again"
    ;;
  *) fail "unexpected seal type '${SEAL_TYPE}'" ;;
esac
ok "initialised: ${INITIALIZED}"

KV_VALUE=$(kv_get) || true
[[ -n "${KV_VALUE}" ]] \
  || fail "Key Vault item ${KEYVAULT_ITEM} not readable in ${KEYVAULT}; create it with value '${PLACEHOLDER}' first"
if [[ "${INITIALIZED}" == "false" ]]; then
  [[ "${KV_VALUE}" == "${PLACEHOLDER}" ]] \
    || fail "vault is not initialised but ${KEYVAULT_ITEM} already holds a key. Is this the right database? Set the item back to '${PLACEHOLDER}' only if that key belongs to a vault that is gone"
  ok "${KEYVAULT_ITEM} holds the placeholder; ready to initialise"
else
  [[ "${KV_VALUE}" != "${PLACEHOLDER}" ]] \
    || fail "vault is initialised but ${KEYVAULT_ITEM} still holds the placeholder: the key was never stored"
  ok "${KEYVAULT_ITEM} holds the key"
fi

kc get secret keycloak-podiumd-realm-secrets -o json 2>/dev/null \
  | jq -e '.data["openbao-oidc-secret"] // empty' >/dev/null \
  || fail "no OpenBao client secret in Secret/keycloak-podiumd-realm-secrets; is the Keycloak realm import deployed?"
ok "Keycloak openbao client secret present"

HAS_GATEWAY=0
if [[ "${NO_READER}" -eq 0 ]] \
  && [[ -n "$(kc get deployment -l app.kubernetes.io/component=frankgateway -o name 2>/dev/null)" ]]; then
  HAS_GATEWAY=1
  ok "Frank!Gateway deployed: its read-only token is managed too"
fi

if [[ "${CHECK_ONLY}" -eq 1 ]]; then
  step "Status"
  RC=0
  for i in $(seq 0 $((REPLICAS - 1))); do
    s=$(pod_status "${STS}-${i}")
    info "${STS}-${i}: $(jq -c '{initialized, sealed}' <<<"${s}")"
    [[ "$(jq -r .sealed <<<"${s}")" == "false" ]] || RC=1
  done
  if [[ "${INITIALIZED}" == "true" ]]; then
    CFG=$(secret_value "${BOOTSTRAP_SECRET}")
    if [[ -n "${CFG}" && -n "$(token_lookup "${STS}-0" "${CFG}")" ]]; then
      ok "config token valid"
    else
      info "config token missing or invalid: run without --check"; RC=1
    fi
    if [[ "${HAS_GATEWAY}" -eq 1 ]]; then
      RD=$(secret_value "${READER_SECRET}")
      LOOKUP=$([[ -n "${RD}" ]] && token_lookup "${STS}-0" "${RD}" || true)
      if [[ -n "${LOOKUP}" ]]; then
        ok "gateway token valid until $(jq -r .data.expire_time <<<"${LOOKUP}")"
      else
        info "gateway token missing or invalid: run without --check"; RC=1
      fi
    fi
  fi
  echo; echo "Check only: nothing changed. Exit code 0 means operational."
  exit "${RC}"
fi

ROOT=""
cleanup() { ROOT=""; KEY=""; KV_VALUE=""; }
trap cleanup EXIT

###############################################################################
step "2. Initialise"
###############################################################################
KEY=""
if [[ "${INITIALIZED}" == "false" ]]; then
  # Write access is checked before init: init returns the key exactly once.
  az keyvault secret set-attributes "${AZ_SUB[@]}" --vault-name "${KEYVAULT}" --name "${KEYVAULT_ITEM}" \
    --tags "openbao=pending-init" -o none \
    || fail "no write access to ${KEYVAULT_ITEM} in ${KEYVAULT}; not initialising"
  if [[ "${SEAL_TYPE}" == "static" ]]; then
    INIT_ARGS="-recovery-shares=1 -recovery-threshold=1"; KEY_FIELD='.recovery_keys_b64[0]'
  else
    INIT_ARGS="-key-shares=1 -key-threshold=1"; KEY_FIELD='.unseal_keys_b64[0]'
  fi
  # shellcheck disable=SC2086
  INIT=$(kc exec "${STS}-0" -c openbao -- bao operator init ${INIT_ARGS} -format=json)
  KEY=$(jq -r "${KEY_FIELD}" <<<"${INIT}")
  ROOT=$(jq -r .root_token <<<"${INIT}")
  INIT=""
  [[ -n "${KEY}" && "${KEY}" != "null" && -n "${ROOT}" && "${ROOT}" != "null" ]] \
    || fail "bao operator init returned no key or root token"
  stored=0
  for attempt in 1 2 3; do
    if az keyvault secret set "${AZ_SUB[@]}" --vault-name "${KEYVAULT}" --name "${KEYVAULT_ITEM}" \
         --file <(printf '%s' "${KEY}") --encoding utf-8 \
         --tags "openbao=$([[ "${SEAL_TYPE}" == static ]] && echo recovery-key || echo unseal-key)" -o none \
       && [[ "$(kv_get)" == "${KEY}" ]]; then
      stored=1; break
    fi
    info "Key Vault write attempt ${attempt} failed; retrying"
    sleep 5
  done
  if [[ "${stored}" -ne 1 ]]; then
    # The key exists nowhere else. Printing it to this run's log is the lesser
    # evil than losing it; rotate it (bao operator rekey) once stored.
    echo "    FAIL  could not store the key in ${KEYVAULT}. Store this value as ${KEYVAULT_ITEM} NOW:" >&2
    echo "${KEY}" >&2
    exit 1
  fi
  ok "initialised; key stored in ${KEYVAULT}/${KEYVAULT_ITEM} and read back"
else
  ok "already initialised"
fi

###############################################################################
step "3. Unseal"
###############################################################################
for i in $(seq 0 $((REPLICAS - 1))); do
  pod="${STS}-${i}"
  if [[ "$(pod_status "${pod}" | jq -r .sealed)" == "true" && "${SEAL_TYPE}" == "shamir" ]]; then
    [[ -n "${KEY}" ]] || KEY=$(kv_get)
    bao_sh "${pod}" >/dev/null <<EOS
bao operator unseal "${KEY}" >/dev/null
EOS
  fi
  for _ in $(seq 1 24); do
    [[ "$(pod_status "${pod}" | jq -r .sealed)" == "false" ]] && break
    sleep 5
  done
  if [[ "$(pod_status "${pod}" | jq -r .sealed)" != "false" && "${SEAL_TYPE}" == "static" ]]; then
    # A standby that started before the vault was initialised can stay sealed;
    # a restart makes it unseal itself with the static key.
    info "${pod} still sealed; restarting it"
    kc delete pod "${pod}" --wait=true >/dev/null
    kc wait --for=condition=Ready "pod/${pod}" --timeout=180s >/dev/null || true
    for _ in $(seq 1 24); do
      [[ "$(pod_status "${pod}" | jq -r .sealed)" == "false" ]] && break
      sleep 5
    done
  fi
  [[ "$(pod_status "${pod}" | jq -r .sealed)" == "false" ]] || fail "${pod} is still sealed"
  ok "${pod} unsealed"
done

###############################################################################
step "4. Tokens"
###############################################################################
CFG=$(secret_value "${BOOTSTRAP_SECRET}")
NEED_CONFIG=${ROTATE_CONFIG}
[[ -n "${CFG}" && -n "$(token_lookup "${STS}-0" "${CFG}")" ]] || NEED_CONFIG=1
NEED_READER=0
if [[ "${HAS_GATEWAY}" -eq 1 ]]; then
  NEED_READER=${ROTATE_READER}
  RD=$(secret_value "${READER_SECRET}")
  [[ -n "${RD}" && -n "$(token_lookup "${STS}-0" "${RD}")" ]] || NEED_READER=1
fi
CFG=""; RD=""

if [[ "${NEED_CONFIG}" -eq 1 || "${NEED_READER}" -eq 1 ]] && [[ -z "${ROOT}" ]]; then
  # Temporary root token from the key in Key Vault; revoked in step 6. OpenBao
  # >= 2.5 only allows unauthenticated generate-root on the loopback listener
  # (127.0.0.1:8210, server.ha.config), so run it on the active pod.
  [[ -n "${KEY}" ]] || KEY=$(kv_get)
  ACTIVE=""
  for i in $(seq 0 $((REPLICAS - 1))); do
    [[ "$(pod_status "${STS}-${i}" | jq -r '.is_self // false')" == "true" ]] && ACTIVE="${STS}-${i}"
  done
  [[ -n "${ACTIVE}" ]] || fail "no active OpenBao pod found"
  LOCAL_ADDR="http://127.0.0.1:8210"
  GEN=$(kc exec "${ACTIVE}" -c openbao -- sh -ec \
    "BAO_ADDR=${LOCAL_ADDR} bao operator generate-root -cancel >/dev/null 2>&1 || true
     BAO_ADDR=${LOCAL_ADDR} bao operator generate-root -init -format=json") \
    || fail "generate-root refused on ${ACTIVE}; does server.ha.config still have the 127.0.0.1:8210 listener?"
  NONCE=$(jq -r .nonce <<<"${GEN}"); OTP=$(jq -r .otp <<<"${GEN}"); GEN=""
  ENCODED=$(bao_sh "${ACTIVE}" <<EOS | jq -r .encoded_token
export BAO_ADDR="${LOCAL_ADDR}"
printf '%s' "${KEY}" | bao operator generate-root -nonce="${NONCE}" -format=json -
EOS
)
  ROOT=$(bao_sh "${ACTIVE}" <<EOS
export BAO_ADDR="${LOCAL_ADDR}"
bao operator generate-root -decode="${ENCODED}" -otp="${OTP}"
EOS
)
  ENCODED=""; OTP=""
  [[ -n "${ROOT}" ]] || fail "could not create a temporary root token"
  ok "temporary root token created from ${KEYVAULT_ITEM}"
fi

if [[ "${NEED_CONFIG}" -eq 1 ]]; then
  BAO_ROOT_TOKEN_FILE=<(printf '%s' "${ROOT}") KUBE_CONTEXT="${KUBE_CONTEXT}" NAMESPACE="${NAMESPACE}" \
    RELEASE="${RELEASE}" BOOTSTRAP_SECRET="${BOOTSTRAP_SECRET}" KV_PATH="${KV_PATH}" \
    TOKEN_PERIOD="${TOKEN_PERIOD}" CALLER_REVOKES_ROOT=1 \
    "${SCRIPT_DIR}/openbao-mint-config-token.sh" 2>&1 | sed 's/^/          /'
  ok "config token minted into Secret/${BOOTSTRAP_SECRET}"
else
  ok "config token valid"
fi

if [[ "${NEED_READER}" -eq 1 ]]; then
  READER=$(bao_sh "${STS}-0" <<EOS
export BAO_ADDR="${BAO_ADDR}" BAO_TOKEN="${ROOT}"
bao policy write frankgateway-reader - >&2 <<'HCL'
path "${READER_MOUNT}/data/frankgateway"   { capabilities = ["read"] }
path "${READER_MOUNT}/data/frankgateway/*" { capabilities = ["read"] }
HCL
bao token create -orphan -policy=frankgateway-reader -period=${READER_PERIOD} \
  -display-name=frankgateway-reader -field=token
EOS
)
  [[ -n "${READER}" ]] || fail "gateway token create returned nothing"
  printf '%s' "${READER}" | kc create secret generic "${READER_SECRET}" \
    --from-file=token=/dev/stdin --dry-run=client -o yaml | kc apply -f - >/dev/null
  READER=""
  kc rollout restart deployment -l app.kubernetes.io/component=frankgateway >/dev/null
  ok "gateway token minted into Secret/${READER_SECRET}; gateways restarted"
elif [[ "${HAS_GATEWAY}" -eq 1 ]]; then
  ok "gateway token valid"
fi

###############################################################################
step "5. Configure (openbao-config Job from the deployed release)"
###############################################################################
JOB_YAML=$(hc get hooks "${RELEASE}" | awk '
  /^---/ { if (doc ~ /kind: Job/ && doc ~ /\n  name: openbao-config\n/) print doc; doc=""; next }
  { doc = doc $0 "\n" }
  END { if (doc ~ /kind: Job/ && doc ~ /\n  name: openbao-config\n/) print doc }')
[[ -n "${JOB_YAML}" ]] || fail "openbao-config Job not found in the release hooks"
kc delete job openbao-config --ignore-not-found --wait=true >/dev/null
printf '%s\n' "${JOB_YAML}" | kc create -f - >/dev/null
kc wait --for=condition=complete job/openbao-config --timeout=300s >/dev/null \
  || { kc logs job/openbao-config | tail -20 >&2; fail "openbao-config Job did not complete"; }
JOB_LOG=$(kc logs job/openbao-config)
if grep -qi 'skipping' <<<"${JOB_LOG}"; then
  echo "${JOB_LOG}" | tail -5 >&2
  fail "openbao-config Job skipped instead of configuring"
fi
ok "openbao-config Job configured the vault"

###############################################################################
step "6. Revoke the root token"
###############################################################################
if [[ -n "${ROOT}" ]]; then
  bao_sh "${STS}-0" >/dev/null <<EOS
export BAO_ADDR="${BAO_ADDR}" BAO_TOKEN="${ROOT}"
bao token revoke -self
EOS
  ROOT=""
  ok "root token revoked; a new one needs ${KEYVAULT_ITEM} (bao operator generate-root, or this script)"
else
  ok "no root token in use"
fi

###############################################################################
step "7. Verify"
###############################################################################
for i in $(seq 0 $((REPLICAS - 1))); do
  s=$(pod_status "${STS}-${i}")
  [[ "$(jq -r .initialized <<<"${s}")/$(jq -r .sealed <<<"${s}")" == "true/false" ]] \
    || fail "${STS}-${i}: $(jq -c '{initialized, sealed}' <<<"${s}")"
done
ok "all ${REPLICAS} pods initialised and unsealed"
CFG=$(secret_value "${BOOTSTRAP_SECRET}")
[[ -n "$(token_lookup "${STS}-0" "${CFG}")" ]] || fail "config token invalid"
CFG=""
ok "config token valid (renewed by every openbao-config run; period ${TOKEN_PERIOD})"
if [[ "${HAS_GATEWAY}" -eq 1 ]]; then
  LOOKUP=$(token_lookup "${STS}-0" "$(secret_value "${READER_SECRET}")")
  [[ -n "${LOOKUP}" ]] || fail "gateway token invalid"
  ok "gateway token valid until $(jq -r .data.expire_time <<<"${LOOKUP}"); renewed weekly by CronJob openbao-token-renewal"
fi

echo
echo "OpenBao is operational. Next: add the people who write secrets to the"
echo "Keycloak group of openbao.configuration.uploadersGroup (default vault-uploaders)."
