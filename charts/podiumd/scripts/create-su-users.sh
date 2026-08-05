#!/usr/bin/env bash
#
# create-su-users.sh — seed per-app "su-<app>" users into a Keycloak realm.
#
# ⚠️  FOR TEST ENVIRONMENTS ONLY. These are convenience superusers with a
#     shared password; never run this against a production realm.
#
# Replaces the former chart-rendered keycloak.config.superuser feature (and the
# OpenBao vault-tester user): the podiumd chart no longer seeds any test or
# su-* users into the realm import. Run this from your own machine instead.
#
# For every app the script:
#   1. looks up the Keycloak client (skips the app if the client is absent);
#   2. creates any missing client role(s) — test realms often run the chart
#      with keycloak.config.skipRoles=true, so roles may not be imported;
#   3. creates the user su-<app> if it does not exist yet;
#   4. (re)sets its password to the shared SU_PASSWORD;
#   5. assigns the app's admin role(s) to the user.
#
# All steps are idempotent — safe to re-run.
#
# Usage:
#   KEYCLOAK_URL=https://keycloak.<env>.example.nl ./create-su-users.sh [app ...]
#
#   With no arguments all known apps are processed; pass app names (e.g.
#   "./create-su-users.sh openbao zac") to limit the run.
#
# Environment:
#   KEYCLOAK_URL             required — Keycloak base URL
#   KEYCLOAK_REALM           realm to seed users into        (default: podiumd)
#   KEYCLOAK_ADMIN_USER      master-realm admin username     (default: admin)
#   KEYCLOAK_ADMIN_PASSWORD  master-realm admin password     (prompted if unset)
#   SU_PASSWORD              shared password for su-* users  (prompted if unset)
#   SU_EMAIL_DOMAIN          email domain for su-* users     (default: example.nl)
#
# Requires: bash 3+, curl, jq.

set -euo pipefail

# --- app => comma-separated client role(s) -----------------------------------
# Mirrors the per-app admin roles previously rendered by the realm import.
APPS=(
  "abc=administrators"
  "openklant=administrators"
  "objecten=administrators"
  "openzaak=administrators"
  "opennotificaties=administrators"
  "openformulieren=administrators"
  "openinwoner=administrators"
  "referentielijsten=administrators"
  "openbeheer=administrators"
  "kiss=Redacteur,Klantcontactmedewerker,Kennisbank"
  "zac=behandelaar,beheerder,coordinator,raadpleger,recordmanager,domein_elk_zaaktype"
  "pabc=administrator"
  "monitoring=admin"
  "ita=ITA_Gebruiker,ITA_Functioneel_Beheerder"
  "openbao=uploaders"
  "zaakbrug=administrators,zaakbrug_admin,dataadmin"
)

usage() {
  sed -n '2,36p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}
[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && usage 0

command -v curl >/dev/null 2>&1 || { echo "ERROR: curl not found" >&2; exit 1; }
command -v jq  >/dev/null 2>&1 || { echo "ERROR: jq not found"  >&2; exit 1; }

KEYCLOAK_URL="${KEYCLOAK_URL:-}"
[[ -n "${KEYCLOAK_URL}" ]] || { echo "ERROR: KEYCLOAK_URL is not set" >&2; usage 1; }
KEYCLOAK_URL="${KEYCLOAK_URL%/}"
KEYCLOAK_REALM="${KEYCLOAK_REALM:-podiumd}"
KEYCLOAK_ADMIN_USER="${KEYCLOAK_ADMIN_USER:-admin}"
SU_EMAIL_DOMAIN="${SU_EMAIL_DOMAIN:-example.nl}"

if [[ -z "${KEYCLOAK_ADMIN_PASSWORD:-}" ]]; then
  read -r -s -p "Keycloak admin password for '${KEYCLOAK_ADMIN_USER}' (master realm): " KEYCLOAK_ADMIN_PASSWORD
  echo >&2
fi
[[ -n "${KEYCLOAK_ADMIN_PASSWORD}" ]] || { echo "ERROR: empty admin password" >&2; exit 1; }

if [[ -z "${SU_PASSWORD:-}" ]]; then
  read -r -s -p "Shared password for the su-* users: " SU_PASSWORD
  echo >&2
  read -r -s -p "Confirm password: " SU_PASSWORD_CONFIRM
  echo >&2
  [[ "${SU_PASSWORD}" == "${SU_PASSWORD_CONFIRM}" ]] || { echo "ERROR: passwords do not match" >&2; exit 1; }
fi
[[ -n "${SU_PASSWORD}" ]] || { echo "ERROR: empty su password" >&2; exit 1; }

# --- Keycloak admin REST helpers ----------------------------------------------
ADMIN_TOKEN=""
TOKEN_BORN=0

fetch_token() {
  local resp
  resp=$(curl -sS --fail-with-body -X POST \
    "${KEYCLOAK_URL}/realms/master/protocol/openid-connect/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "grant_type=password" \
    --data-urlencode "client_id=admin-cli" \
    --data-urlencode "username=${KEYCLOAK_ADMIN_USER}" \
    --data-urlencode "password=${KEYCLOAK_ADMIN_PASSWORD}") \
    || { echo "ERROR: could not obtain admin token from ${KEYCLOAK_URL} (check URL/credentials)" >&2; exit 1; }
  ADMIN_TOKEN=$(printf '%s' "${resp}" | jq -r '.access_token // empty')
  [[ -n "${ADMIN_TOKEN}" ]] || { echo "ERROR: token response contained no access_token" >&2; exit 1; }
  TOKEN_BORN=${SECONDS}
}

# kc_api METHOD PATH [JSON_BODY]
# Prints the response body; returns non-zero and prints the HTTP code to
# stderr on a >=400 response. Refreshes the token when it nears expiry.
KC_LAST_CODE=""
kc_api() {
  local method="$1" path="$2" body="${3:-}"
  local resp code
  if [[ -z "${ADMIN_TOKEN}" ]] || (( SECONDS - TOKEN_BORN >= 45 )); then
    fetch_token
  fi
  if [[ -n "${body}" ]]; then
    resp=$(curl -sS -w $'\n%{http_code}' -X "${method}" \
      "${KEYCLOAK_URL}/admin/realms/${KEYCLOAK_REALM}${path}" \
      -H "Authorization: Bearer ${ADMIN_TOKEN}" \
      -H "Content-Type: application/json" \
      --data "${body}")
  else
    resp=$(curl -sS -w $'\n%{http_code}' -X "${method}" \
      "${KEYCLOAK_URL}/admin/realms/${KEYCLOAK_REALM}${path}" \
      -H "Authorization: Bearer ${ADMIN_TOKEN}")
  fi
  code="${resp##*$'\n'}"
  KC_LAST_CODE="${code}"
  printf '%s' "${resp%$'\n'*}"
  [[ "${code}" -lt 400 ]]
}

# --- per-app worker ------------------------------------------------------------
process_app() {
  local app="$1" roles_csv="$2"
  local username="su-${app}"
  local clients client_id user_json user_id role_json role_id role assign_json
  local created=0

  # 1. client lookup — absent client means the app is not deployed here
  clients=$(kc_api GET "/clients?clientId=${app}") \
    || { echo "  SKIP ${app}: client lookup failed (HTTP ${KC_LAST_CODE})" >&2; return 0; }
  client_id=$(printf '%s' "${clients}" | jq -r '.[0].id // empty')
  if [[ -z "${client_id}" ]]; then
    echo "  SKIP ${app}: no Keycloak client '${app}' in realm '${KEYCLOAK_REALM}'"
    return 0
  fi

  # 2. ensure the client role(s) exist
  local old_ifs="${IFS}"
  IFS=','
  # shellcheck disable=SC2206  # intentional word splitting on commas
  local roles=(${roles_csv})
  IFS="${old_ifs}"

  for role in "${roles[@]}"; do
    if ! kc_api GET "/clients/${client_id}/roles/${role}" >/dev/null; then
      kc_api POST "/clients/${client_id}/roles" "$(jq -n --arg n "${role}" '{name:$n}')" >/dev/null \
        || { echo "  ERROR ${app}: could not create role '${role}' (HTTP ${KC_LAST_CODE})" >&2; return 1; }
      echo "  created client role ${app}:${role}"
    fi
  done

  # 3. ensure the user exists
  user_json=$(kc_api GET "/users?username=${username}&exact=true") \
    || { echo "  ERROR ${app}: user lookup failed (HTTP ${KC_LAST_CODE})" >&2; return 1; }
  user_id=$(printf '%s' "${user_json}" | jq -r '.[0].id // empty')
  if [[ -z "${user_id}" ]]; then
    kc_api POST "/users" "$(jq -n \
      --arg u "${username}" --arg app "${app}" --arg e "${username}@${SU_EMAIL_DOMAIN}" \
      '{username:$u, enabled:true, emailVerified:true,
        firstName:"Superuser", lastName:$app, email:$e}')" >/dev/null \
      || { echo "  ERROR ${app}: could not create user '${username}' (HTTP ${KC_LAST_CODE})" >&2; return 1; }
    user_json=$(kc_api GET "/users?username=${username}&exact=true")
    user_id=$(printf '%s' "${user_json}" | jq -r '.[0].id // empty')
    [[ -n "${user_id}" ]] || { echo "  ERROR ${app}: user created but not found on re-read" >&2; return 1; }
    created=1
  fi

  # 4. (re)set the shared password
  kc_api PUT "/users/${user_id}/reset-password" "$(jq -n --arg p "${SU_PASSWORD}" \
    '{type:"password", value:$p, temporary:false}')" >/dev/null \
    || { echo "  ERROR ${app}: could not set password for '${username}' (HTTP ${KC_LAST_CODE})" >&2; return 1; }

  # 5. assign the client role(s)
  assign_json="[]"
  for role in "${roles[@]}"; do
    role_json=$(kc_api GET "/clients/${client_id}/roles/${role}") \
      || { echo "  ERROR ${app}: could not read role '${role}' (HTTP ${KC_LAST_CODE})" >&2; return 1; }
    role_id=$(printf '%s' "${role_json}" | jq -r '.id // empty')
    assign_json=$(printf '%s' "${assign_json}" | jq --arg id "${role_id}" --arg n "${role}" \
      '. + [{id:$id, name:$n}]')
  done
  kc_api POST "/users/${user_id}/role-mappings/clients/${client_id}" "${assign_json}" >/dev/null \
    || { echo "  ERROR ${app}: could not assign roles (HTTP ${KC_LAST_CODE})" >&2; return 1; }

  if [[ "${created}" -eq 1 ]]; then
    echo "  OK ${username}: created, roles [${roles_csv}]"
  else
    echo "  OK ${username}: already existed, password reset, roles [${roles_csv}]"
  fi
}

# --- main ----------------------------------------------------------------------
echo "Seeding su-* users into realm '${KEYCLOAK_REALM}' at ${KEYCLOAK_URL}"
echo "⚠️  Test environments only — do not run against production."

fetch_token

rc=0
for entry in "${APPS[@]}"; do
  app="${entry%%=*}"
  roles_csv="${entry#*=}"
  if [[ "$#" -gt 0 ]]; then
    wanted=0
    for arg in "$@"; do
      [[ "${arg}" == "${app}" ]] && wanted=1
    done
    [[ "${wanted}" -eq 1 ]] || continue
  fi
  process_app "${app}" "${roles_csv}" || rc=1
done

exit "${rc}"
