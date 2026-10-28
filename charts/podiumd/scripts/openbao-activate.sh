#!/usr/bin/env bash
#
# openbao-activate.sh — make the in-chart OpenBao operational after a deploy,
# in one run: check, initialise, unseal, mint the tokens, configure, verify.
#
# Run it after the `helm upgrade` that deployed OpenBao, from a pipeline step
# or an operator machine. It is idempotent: on an operational vault it mints
# nothing and only re-runs the openbao-config Job (step 5), so it can run after
# every deploy. --check changes nothing at all.
#
# What one run does:
#   1. Preflight (read-only, stops on the first problem): cluster, release,
#      OpenBao pods, seal type, Key Vault item, Keycloak client secret.
#   2. Initialise, when the vault is not initialised yet. The one key OpenBao
#      returns (the recovery key with the static seal, the unseal key with
#      Shamir) goes to Key Vault item KEYVAULT_ITEM and is read back. This is
#      the ONLY Key Vault write the script does. The init output first goes to
#      a mode-0600 file in pod 0 (INIT_FILE) and is removed only after the Key
#      Vault read-back matches, so a broken `kubectl exec` cannot lose the key:
#      a rerun finds the vault initialised, Key Vault still at the placeholder,
#      and stores the key from that file.
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
#      key in Key Vault (legacy sys/generate-root API) when it has to mint a
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
#   --force                  Cancel a generate-root attempt that is already in
#                            progress (another operator or pipeline run) instead
#                            of stopping.
#   --revoke-accessor ACC    Revoke the token with accessor ACC, using this run's
#                            temporary root token: for a root token an earlier
#                            run could not revoke (it prints the accessor).
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
#   READER_SECRET       frankgateway.openbao.tokenSecret.name (default: frankgateway-openbao-token)
#   READER_SECRET_KEY   frankgateway.openbao.tokenSecret.key  (default: token)
#   READER_KV_VERSION   frankgateway.openbao.kvVersion, 1 or 2 (default: 2)
#   READER_PERIOD       renewal period of the gateway token (default: 768h = 32 days)
#   BOOTSTRAP_SECRET    openbao.configuration.bootstrapTokenSecret
#                                                    (default: openbao-bootstrap-token)
#   TOKEN_PERIOD        renewal period of the config token (default: 768h = 32 days)
#
# Key Vault item KEYVAULT_ITEM must exist before the first run, holding the
# placeholder value `pending-init` (create it with the other items from the
# pipeline). The script refuses to overwrite any other value.
#
# Requires: bash 4+, kubectl, helm 3+, az, jq, python3. Exit code 0 means operational.

set -euo pipefail

# The whole header comment, however long it gets: from line 2 to the first
# line that isn't a comment.
usage() {
  awk 'NR > 1 && !/^#/ { exit } NR > 1' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

CHECK_ONLY=0
ROTATE_CONFIG=0
ROTATE_READER=0
NO_READER=0
ALLOW_SHAMIR=0
RECOVER_INIT=0
FORCE=0
REVOKE_ACCESSOR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --check)               CHECK_ONLY=1 ;;
    --rotate-config-token) ROTATE_CONFIG=1 ;;
    --rotate-reader-token) ROTATE_READER=1 ;;
    --no-reader-token)     NO_READER=1 ;;
    --allow-shamir)        ALLOW_SHAMIR=1 ;;
    --force)               FORCE=1 ;;
    --revoke-accessor)     REVOKE_ACCESSOR="${2:?--revoke-accessor needs an accessor}"; shift ;;
    -h|--help)             usage 0 ;;
    *) echo "ERROR: unknown argument '$1'" >&2; usage 1 ;;
  esac
  shift
done

for cmd in kubectl helm az jq python3; do
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
READER_SECRET_KEY="${READER_SECRET_KEY:-token}"
READER_KV_VERSION="${READER_KV_VERSION:-2}"
case "${READER_KV_VERSION}" in
  2) READER_PATH="${READER_MOUNT}/data/frankgateway" ;;
  1) READER_PATH="${READER_MOUNT}/frankgateway" ;;
  *) echo "ERROR: READER_KV_VERSION must be 1 or 2" >&2; exit 1 ;;
esac
READER_PERIOD="${READER_PERIOD:-768h}"
BOOTSTRAP_SECRET="${BOOTSTRAP_SECRET:-openbao-bootstrap-token}"
TOKEN_PERIOD="${TOKEN_PERIOD:-768h}"
PLACEHOLDER="pending-init"
STS="${RELEASE}-openbao"
# `bao operator init` output, in pod 0, until the key is safe in Key Vault.
INIT_FILE="/tmp/.openbao-init.json"
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

bao_any() {
  # Runs the script on stdin with bao_sh on the first pod that takes it: the
  # active pod when known, then pod 0, 1, ... A standby forwards the request to
  # the active node, so one pod that cannot be exec'd into does not block it.
  local script pod i
  script=$(cat)
  for pod in ${ACTIVE:-} $(for i in $(seq 0 $((REPLICAS - 1))); do echo "${STS}-${i}"; done); do
    printf '%s\n' "${script}" | bao_sh "${pod}" && return 0
  done
  return 1
}

pod_status() {
  # `bao status` exits 2 when sealed; the JSON is what counts.
  kc exec "$1" -c openbao -- bao status -format=json 2>/dev/null || true
}

kv_get() {
  az keyvault secret show "${AZ_SUB[@]}" --vault-name "${KEYVAULT}" --name "${KEYVAULT_ITEM}" \
    --query value -o tsv 2>/dev/null
}

init_file() {
  # The init output kept in pod 0, or nothing.
  kc exec "${STS}-0" -c openbao -- cat "${INIT_FILE}" 2>/dev/null || true
}

secret_value() {
  # secret_value <secret> [key, default token]
  kc get secret "$1" -o jsonpath="{.data.${2:-token}}" 2>/dev/null | base64 -d 2>/dev/null || true
}

token_valid() {
  # token_valid <pod> <token>: 0 and the lookup JSON in LOOKUP when OpenBao
  # accepts the token, 1 when it rejects it (403 permission denied). Any other
  # failure (no active pod, a transport error) stops the run: treating it as
  # "invalid" would mint a new token and leave the old one valid.
  local err
  LOOKUP=""
  [[ -n "$2" ]] || return 1
  err=$(mktemp)
  if LOOKUP=$(bao_sh "$1" 2>"${err}" <<EOS
export BAO_ADDR="${BAO_ADDR}" BAO_TOKEN="$2"
bao token lookup -format=json
EOS
); then
    rm -f "${err}"; return 0
  fi
  LOOKUP=""
  if grep -qiE 'permission denied|Code: 403' "${err}"; then
    rm -f "${err}"; return 1
  fi
  echo "          $(tail -1 "${err}")" >&2; rm -f "${err}"
  fail "token lookup through ${BAO_ADDR} failed (is OpenBao reachable and unsealed?)"
}

###############################################################################
step "1. Preflight (read-only)"
###############################################################################
kc get namespace "${NAMESPACE}" >/dev/null 2>&1 \
  || kc get pods --field-selector=status.phase=Running -o name >/dev/null \
  || fail "cannot reach namespace ${NAMESPACE} on context ${KUBE_CONTEXT}"
ok "cluster reachable (context ${KUBE_CONTEXT}, namespace ${NAMESPACE})"

# Not `helm status`: Helm 4 lists every release resource there, a minute on a busy cluster.
hc get metadata "${RELEASE}" >/dev/null 2>&1 || fail "Helm release ${RELEASE} not found"
# Captured first: `grep -q` exits on the first match, and under pipefail the
# SIGPIPE that gives helm would fail this check on a large hooks output.
HOOKS=$(hc get hooks "${RELEASE}") || fail "helm get hooks ${RELEASE} failed"
grep -q 'name: openbao-config' <<<"${HOOKS}" \
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
  [[ -z "$(init_file)" ]] \
    || fail "vault is not initialised but ${STS}-0 already has ${INIT_FILE}: another run is initialising it, or the file is left from a vault that is gone. Check, and remove the file only if its key is not needed"
  ok "${KEYVAULT_ITEM} holds the placeholder; ready to initialise"
elif [[ "${KV_VALUE}" == "${PLACEHOLDER}" ]]; then
  # An earlier run initialised the vault but did not get the key into Key Vault.
  [[ -n "$(init_file)" ]] \
    || fail "vault is initialised but ${KEYVAULT_ITEM} still holds the placeholder and ${STS}-0 has no ${INIT_FILE}: the key is lost. Wipe and re-initialise (frankgateway-openbao.md §3.6, Interrupted init)"
  RECOVER_INIT=1
  info "vault is initialised but the key is not in Key Vault yet; storing it from ${STS}-0:${INIT_FILE}"
else
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
  [[ "${RECOVER_INIT}" -eq 1 ]] && { info "key not in Key Vault yet: run without --check to store it"; RC=1; }
  for i in $(seq 0 $((REPLICAS - 1))); do
    s=$(pod_status "${STS}-${i}")
    info "${STS}-${i}: $(jq -c '{initialized, sealed}' <<<"${s}")"
    [[ "$(jq -r .sealed <<<"${s}")" == "false" ]] || RC=1
  done
  if [[ "${INITIALIZED}" == "true" ]]; then
    CFG=$(secret_value "${BOOTSTRAP_SECRET}")
    if token_valid "${STS}-0" "${CFG}"; then
      ok "config token valid"
    else
      info "config token missing or invalid: run without --check"; RC=1
    fi
    if [[ "${HAS_GATEWAY}" -eq 1 ]]; then
      RD=$(secret_value "${READER_SECRET}" "${READER_SECRET_KEY}")
      if token_valid "${STS}-0" "${RD}"; then
        ok "gateway token valid until $(jq -r .data.expire_time <<<"${LOOKUP}")"
      else
        info "gateway token missing or invalid: run without --check"; RC=1
      fi
    fi
  fi
  echo; echo "Check only: nothing changed. Exit code 0 means operational."
  exit "${RC}"
fi

ROOT=""; ROOT_ACCESSOR=""; ACTIVE=""; GEN_ROOT_ACTIVE=""
revoke_root() {
  bao_any >/dev/null 2>&1 <<EOS
export BAO_ADDR="${BAO_ADDR}" BAO_TOKEN="${ROOT}"
bao token revoke -self
EOS
}
remember_root_accessor() {
  # Best effort: only for the hint when the root token cannot be revoked.
  ROOT_ACCESSOR=$(bao_any 2>/dev/null <<EOS | jq -r '.data.accessor // empty' || true
export BAO_ADDR="${BAO_ADDR}" BAO_TOKEN="${ROOT}"
bao token lookup -format=json
EOS
)
}
# On any exit, also a failed step: revoke a root token that is still live
# (init and generate-root tokens never expire), then clear the secrets.
cleanup() {
  if [[ -n "${GEN_ROOT_ACTIVE}" ]]; then
    # This run started a generate-root attempt that did not finish: cancel it,
    # so the next run does not take it for another operator's attempt.
    if kc exec "${GEN_ROOT_ACTIVE}" -c openbao -- sh -ec \
         "BAO_ADDR=http://127.0.0.1:8210 bao delete sys/generate-root/attempt" >/dev/null 2>&1; then
      echo "    ..    generate-root attempt of this run cancelled on exit" >&2
    else
      echo "    WARN  could not cancel this run's generate-root attempt on ${GEN_ROOT_ACTIVE};" >&2
      echo "          the next run needs --force to cancel it" >&2
    fi
  fi
  if [[ -n "${ROOT}" ]]; then
    if revoke_root; then
      echo "    ..    root token revoked on exit" >&2
    else
      echo "    WARN  could not revoke the root token on any OpenBao pod; it does not expire." >&2
      if [[ -n "${ROOT_ACCESSOR}" ]]; then
        echo "          Once OpenBao is reachable, run this script with --revoke-accessor ${ROOT_ACCESSOR}" >&2
      else
        echo "          Its accessor is unknown: once OpenBao is unsealed, find the root token's accessor" >&2
        echo "          (bao list auth/token/accessors, then bao token lookup -accessor <accessor>)" >&2
        echo "          and run this script with --revoke-accessor <accessor>" >&2
      fi
    fi
  fi
  ROOT=""; KEY=""; KV_VALUE=""; OLD_CFG=""; OLD_RD=""
}
trap cleanup EXIT

###############################################################################
step "2. Initialise"
###############################################################################
KEY=""
if [[ "${SEAL_TYPE}" == "static" ]]; then
  INIT_ARGS="-recovery-shares=1 -recovery-threshold=1"; KEY_FIELD='.recovery_keys_b64[0]'
else
  INIT_ARGS="-key-shares=1 -key-threshold=1"; KEY_FIELD='.unseal_keys_b64[0]'
fi
if [[ "${INITIALIZED}" == "false" ]]; then
  # Write access is checked before init: init returns the key exactly once.
  az keyvault secret set-attributes "${AZ_SUB[@]}" --vault-name "${KEYVAULT}" --name "${KEYVAULT_ITEM}" \
    --tags "openbao=pending-init" -o none \
    || fail "no write access to ${KEYVAULT_ITEM} in ${KEYVAULT}; not initialising"
  # The output stays in the pod (mode 0600) until Key Vault holds the key: if
  # this exec breaks after the server initialised, a rerun stores it from there.
  # It is written to a temporary file and linked into place only when init
  # succeeds: a concurrent run, whose init fails with "already initialized",
  # then cannot empty the file of the run that did initialise. `ln` fails if
  # the file exists, so it never overwrites another run's key either.
  INIT_TMP="${INIT_FILE}.$$"
  kc exec "${STS}-0" -c openbao -- sh -ec \
    "umask 077; bao operator init ${INIT_ARGS} -format=json > ${INIT_TMP} || { rm -f ${INIT_TMP}; exit 1; }; ln ${INIT_TMP} ${INIT_FILE} || { echo 'init output kept in ${INIT_TMP}: ${INIT_FILE} already exists' >&2; exit 1; }; rm -f ${INIT_TMP}" \
    || fail "bao operator init failed on ${STS}-0. If the vault is initialised now, run this script again: it stores the key from ${STS}-0:${INIT_FILE}"
  RECOVER_INIT=1
fi
if [[ "${RECOVER_INIT}" -eq 1 ]]; then
  INIT=$(init_file)
  KEY=$(jq -r "${KEY_FIELD}" <<<"${INIT}") || fail "${STS}-0:${INIT_FILE} is not valid init output"
  ROOT=$(jq -r .root_token <<<"${INIT}") || fail "${STS}-0:${INIT_FILE} is not valid init output"
  INIT=""
  [[ -n "${KEY}" && "${KEY}" != "null" && -n "${ROOT}" && "${ROOT}" != "null" ]] \
    || fail "${STS}-0:${INIT_FILE} holds no key or root token"
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
    # The key stays in ${INIT_FILE} for a rerun. Also keep a copy on this
    # machine, in a 0600 file, and print only its path: a pipeline log is
    # kept and unmasked. The key itself goes to stderr only on a terminal.
    KEY_COPY=$(umask 077; mktemp "${TMPDIR:-/tmp}/openbao-key.XXXXXX")
    printf '%s\n' "${KEY}" > "${KEY_COPY}"
    echo "    FAIL  could not store the key in ${KEYVAULT}/${KEYVAULT_ITEM}. It is kept in" >&2
    echo "          ${STS}-0:${INIT_FILE} (rerun this script to store it from there) and in" >&2
    echo "          ${KEY_COPY} on this machine (mode 0600). Store it, then delete that file." >&2
    [[ -t 2 ]] && echo "${KEY}" >&2
    exit 1
  fi
  kc exec "${STS}-0" -c openbao -- rm -f "${INIT_FILE}" \
    || info "could not remove ${STS}-0:${INIT_FILE}; it holds the key and the root token: delete it"
  ok "initialised; key stored in ${KEYVAULT}/${KEYVAULT_ITEM} and read back"
  # The init root token is checked after step 3: with the Shamir seal the pods
  # are still sealed here, and a lookup on a sealed vault fails.
  remember_root_accessor
else
  ok "already initialised"
fi

###############################################################################
step "3. Unseal"
###############################################################################
for i in $(seq 0 $((REPLICAS - 1))); do
  pod="${STS}-${i}"
  if [[ "$(pod_status "${pod}" | jq -r .sealed)" == "true" && "${SEAL_TYPE}" == "shamir" ]]; then
    [[ -n "${KEY}" ]] || KEY=$(kv_get) || fail "cannot read ${KEYVAULT_ITEM} from ${KEYVAULT}"
    # Key on stdin (key=-), not as an argument of a process in the pod.
    bao_sh "${pod}" >/dev/null <<EOS || fail "unseal of ${pod} failed with the key from ${KEYVAULT_ITEM}"
printf '%s' "${KEY}" | bao write -format=json sys/unseal key=- >/dev/null
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
# Stored on a rerun: the failed run revoked the init root token on exit;
# step 4 then creates a temporary one from the key, as on any initialised vault.
if [[ -n "${ROOT}" && "${INITIALIZED}" == "true" ]]; then
  if token_valid "${STS}-0" "${ROOT}"; then
    remember_root_accessor
  else
    ROOT=""
    info "the init root token is no longer valid; a temporary one is created when needed"
  fi
elif [[ -n "${ROOT}" && -z "${ROOT_ACCESSOR}" ]]; then
  remember_root_accessor
fi

###############################################################################
step "4. Tokens"
###############################################################################
# A valid token that is replaced on request (--rotate-*) is revoked once its
# successor is in place, so a rotation leaves no second valid token behind.
OLD_CFG=""; OLD_RD=""
CFG=$(secret_value "${BOOTSTRAP_SECRET}")
NEED_CONFIG=${ROTATE_CONFIG}
if token_valid "${STS}-0" "${CFG}"; then
  [[ "${ROTATE_CONFIG}" -eq 1 ]] && OLD_CFG="${CFG}"
else
  NEED_CONFIG=1
fi
NEED_READER=0
if [[ "${HAS_GATEWAY}" -eq 1 ]]; then
  NEED_READER=${ROTATE_READER}
  RD=$(secret_value "${READER_SECRET}" "${READER_SECRET_KEY}")
  if token_valid "${STS}-0" "${RD}"; then
    [[ "${ROTATE_READER}" -eq 1 ]] && OLD_RD="${RD}"
  else
    NEED_READER=1
  fi
fi
CFG=""; RD=""

revoke_token() {
  # revoke_token <label> <token>: revoke a replaced token with the root token.
  bao_any >/dev/null <<EOS || fail "could not revoke the previous $1. The new one is stored; the old one stays valid until its period ends without renewal, or until you revoke it with --revoke-accessor <its accessor>"
export BAO_ADDR="${BAO_ADDR}" BAO_TOKEN="${ROOT}"
printf '%s' "$2" | bao write auth/token/revoke token=- >/dev/null
EOS
  ok "previous $1 revoked"
}

if [[ "${NEED_CONFIG}" -eq 1 || "${NEED_READER}" -eq 1 || -n "${REVOKE_ACCESSOR}" ]] && [[ -z "${ROOT}" ]]; then
  # Temporary root token from the key in Key Vault; revoked in step 6. OpenBao
  # >= 2.5.3 only allows unauthenticated generate-root on the loopback listener
  # (127.0.0.1:8210, server.ha.config), so run it on the active pod.
  [[ -n "${KEY}" ]] || KEY=$(kv_get) || fail "cannot read ${KEYVAULT_ITEM} from ${KEYVAULT}"
  ACTIVE=""
  for i in $(seq 0 $((REPLICAS - 1))); do
    [[ "$(pod_status "${STS}-${i}" | jq -r '.is_self // false')" == "true" ]] && ACTIVE="${STS}-${i}"
  done
  [[ -n "${ACTIVE}" ]] || fail "no active OpenBao pod found"
  LOCAL_ADDR="http://127.0.0.1:8210"
  # The bao 2.x CLI (`bao operator generate-root`) calls the authenticated
  # sys/generate-root-token/* endpoints, which need a token; use the legacy
  # sys/generate-root/* endpoints instead, which the loopback listener allows.
  # Another operator's or pipeline run's attempt is not cancelled silently:
  # both runs would race and one would fail.
  STARTED=$(kc exec "${ACTIVE}" -c openbao -- sh -ec \
    "BAO_ADDR=${LOCAL_ADDR} bao read -format=json sys/generate-root/attempt" | jq -r '.data.started // false') \
    || fail "generate-root refused on ${ACTIVE}; does server.ha.config still have the 127.0.0.1:8210 listener?"
  if [[ "${STARTED}" == "true" ]]; then
    [[ "${FORCE}" -eq 1 ]] \
      || fail "a generate-root attempt is already in progress on ${ACTIVE} (another operator or pipeline run?). Wait for it, or rerun with --force to cancel it"
    kc exec "${ACTIVE}" -c openbao -- sh -ec "BAO_ADDR=${LOCAL_ADDR} bao delete sys/generate-root/attempt" >/dev/null \
      || fail "could not cancel the generate-root attempt on ${ACTIVE}"
    info "cancelled the generate-root attempt in progress (--force)"
  fi
  GEN=$(kc exec "${ACTIVE}" -c openbao -- sh -ec \
    "BAO_ADDR=${LOCAL_ADDR} bao write -f -format=json sys/generate-root/attempt") \
    || fail "generate-root refused on ${ACTIVE}; does server.ha.config still have the 127.0.0.1:8210 listener?"
  GEN_ROOT_ACTIVE="${ACTIVE}"
  NONCE=$(jq -r .data.nonce <<<"${GEN}"); OTP=$(jq -r .data.otp <<<"${GEN}"); GEN=""
  [[ -n "${NONCE}" && "${NONCE}" != "null" && -n "${OTP}" && "${OTP}" != "null" ]] \
    || fail "generate-root attempt returned no nonce/OTP"
  ENCODED=$(bao_sh "${ACTIVE}" <<EOS | jq -r '.data.encoded_token // empty'
export BAO_ADDR="${LOCAL_ADDR}"
printf '%s' "${KEY}" | bao write -format=json sys/generate-root/update nonce="${NONCE}" key=-
EOS
) || fail "generate-root did not accept the key from ${KEYVAULT_ITEM}"
  [[ -n "${ENCODED}" ]] || fail "generate-root did not complete with the key from ${KEYVAULT_ITEM}"
  # The attempt is complete once the encoded token is returned: nothing to cancel.
  GEN_ROOT_ACTIVE=""
  # encoded_token = base64(token XOR otp); decode locally, nothing leaves this machine.
  ROOT=$(ENC="${ENCODED}" OTP="${OTP}" python3 -c '
import base64, os
enc = os.environ["ENC"]; otp = os.environ["OTP"].encode()
raw = base64.b64decode(enc + "=" * (-len(enc) % 4))
print(bytes(a ^ b for a, b in zip(raw, otp)).decode(), end="")') \
    || fail "could not decode the generate-root token"
  ENCODED=""; OTP=""
  [[ -n "${ROOT}" ]] || fail "could not create a temporary root token"
  remember_root_accessor
  ok "temporary root token created from ${KEYVAULT_ITEM}"
fi

if [[ -n "${REVOKE_ACCESSOR}" ]]; then
  bao_any >/dev/null <<EOS || fail "could not revoke the token with accessor ${REVOKE_ACCESSOR}"
export BAO_ADDR="${BAO_ADDR}" BAO_TOKEN="${ROOT}"
bao write auth/token/revoke-accessor accessor="${REVOKE_ACCESSOR}" >/dev/null
EOS
  ok "token with accessor ${REVOKE_ACCESSOR} revoked"
fi

if [[ "${NEED_CONFIG}" -eq 1 ]]; then
  BAO_ROOT_TOKEN_FILE=<(printf '%s' "${ROOT}") KUBE_CONTEXT="${KUBE_CONTEXT}" NAMESPACE="${NAMESPACE}" \
    RELEASE="${RELEASE}" BOOTSTRAP_SECRET="${BOOTSTRAP_SECRET}" KV_PATH="${KV_PATH}" \
    TOKEN_PERIOD="${TOKEN_PERIOD}" CALLER_REVOKES_ROOT=1 \
    "${SCRIPT_DIR}/openbao-mint-config-token.sh" 2>&1 | sed 's/^/          /'
  ok "config token minted into Secret/${BOOTSTRAP_SECRET}"
  [[ -n "${OLD_CFG}" ]] && revoke_token "config token" "${OLD_CFG}"
  OLD_CFG=""
else
  ok "config token valid"
fi

if [[ "${NEED_READER}" -eq 1 ]]; then
  READER=$(bao_sh "${STS}-0" <<EOS
export BAO_ADDR="${BAO_ADDR}" BAO_TOKEN="${ROOT}"
bao policy write frankgateway-reader - >&2 <<'HCL'
path "${READER_PATH}"   { capabilities = ["read"] }
path "${READER_PATH}/*" { capabilities = ["read"] }
HCL
bao token create -orphan -policy=frankgateway-reader -period=${READER_PERIOD} \
  -display-name=frankgateway-reader -field=token
EOS
) || fail "gateway token create failed"
  [[ -n "${READER}" ]] || fail "gateway token create returned nothing"
  printf '%s' "${READER}" | kc create secret generic "${READER_SECRET}" \
    --from-file="${READER_SECRET_KEY}"=/dev/stdin --dry-run=client -o yaml | kc apply -f - >/dev/null
  READER=""
  kc rollout restart deployment -l app.kubernetes.io/component=frankgateway >/dev/null
  # Revoke the old token only once every gateway pod runs with the new one.
  # Without an old token to revoke (fresh install, invalid token) nothing waits on the rollout.
  if [[ -n "${OLD_RD}" ]]; then
    for d in $(kc get deployment -l app.kubernetes.io/component=frankgateway -o name); do
      kc rollout status "${d}" --timeout=300s >/dev/null || fail "${d} did not roll out with the new token"
    done
  fi
  ok "gateway token minted into Secret/${READER_SECRET}; gateways restarted"
  [[ -n "${OLD_RD}" ]] && revoke_token "gateway token" "${OLD_RD}"
  OLD_RD=""
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
# Poll the Job's conditions: `kubectl wait --for=condition=complete` would sit
# out the whole timeout on a Job that has already failed.
JOB_STATE=""
for _ in $(seq 1 60); do
  JOB_STATE=$(kc get job openbao-config -o jsonpath='{.status.conditions[?(@.status=="True")].type}' 2>/dev/null || true)
  [[ "${JOB_STATE}" == *Complete* || "${JOB_STATE}" == *Failed* ]] && break
  sleep 5
done
if [[ "${JOB_STATE}" != *Complete* ]]; then
  kc logs job/openbao-config | tail -20 >&2
  fail "openbao-config Job did not complete (${JOB_STATE:-still running after 300s})"
fi
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
  revoke_root || fail "could not revoke the root token on any OpenBao pod"
  ROOT=""
  ok "root token revoked; a new one needs ${KEYVAULT_ITEM} (run this script with --rotate-*)"
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
token_valid "${STS}-0" "${CFG}" || fail "config token invalid"
CFG=""
ok "config token valid (renewed by every openbao-config run; period ${TOKEN_PERIOD})"
if [[ "${HAS_GATEWAY}" -eq 1 ]]; then
  token_valid "${STS}-0" "$(secret_value "${READER_SECRET}" "${READER_SECRET_KEY}")" || fail "gateway token invalid"
  ok "gateway token valid until $(jq -r .data.expire_time <<<"${LOOKUP}"); renewed weekly by CronJob openbao-token-renewal"
fi

echo
echo "OpenBao is operational. Next: add the people who write secrets to the"
echo "Keycloak group of openbao.configuration.uploadersGroup (default vault-uploaders)."
