#!/usr/bin/env bash
#
# Copy the API tokens that exist only in the objecttypen database into the
# objecten database, before the PodiumD 4.10.0 upgrade (Objecten 4 merge).
#
# Run per environment while objecttypen (objecttypes-api 3.4.x) and objecten
# (objects-api 3.6.x) both still run, after `import_objecttypes` and before
# `helm upgrade` to 4.10.0. Dry-run by default; --apply writes.
#
# Why: after the upgrade objecten (Open Object 4) serves the Objecttypen API,
# so every token a consumer sends to the old objecttypen hostname must be a
# token of objecten. `import_objecttypes` copies objecttypes only, and
# migrate-objecten-4.1.0.py merges only the tokens in the values
# (objecttypen.configuration.data tokenauth). Tokens created by hand in the
# objecttypen admin would stop working at cutover.
#
# What it does, per objecttypen token:
#   exists-same-token   objecten already has this token value: nothing to do
#   skipped             the identifier is in objecttypen's configuration
#                       (ConfigMap objecttypen-configuration): the values
#                       migration merges it into objecten's configuration and
#                       the 4.10.0 config job creates it; copying it here too
#                       could create the same token under a second identifier
#   created             new objecten token, same identifier
#   created-as-renamed  objecten already uses the identifier (for another
#                       token): created as <identifier>-objecttypen (unique)
# A created token gets the identifier, token, contact_person, email,
# organization, application and administration of the objecttypen token, is
# NOT a superuser and gets NO object type permissions: in objects-api 3.6 it
# can do nothing, in Open Object 4 it can use the Objecttypen API endpoints,
# which only require a valid token (as in objecttypes-api 3.4). Nothing in
# objecttypen is changed.
#
# Token values are never printed, logged or written to disk: they go from the
# objecttypen pod to the objecten pod through a pipe (kubectl exec stdout ->
# kubectl exec stdin). The report shows identifiers and the first 12
# characters of the token's sha256 only. Running it again creates nothing.
#
# Requires: kubectl with pods/exec rights in the namespace.

set -euo pipefail

SCRIPT_NAME="$(basename "${0}")"
CONTEXT=""
NAMESPACE="podiumd"
APPLY=false
CONFIGMAP=""
OBJECTTYPEN_DEPLOY="objecttypen"
OBJECTEN_DEPLOY="objecten"

print_usage() {
  cat <<EOF
Usage:
  ${SCRIPT_NAME} --context CONTEXT [--namespace NS] [--dry-run | --apply] [--configmap NAME]

Copy tokens that exist only in the objecttypen database into objecten (PodiumD
4.10.0 pre-deploy step). Dry-run unless --apply is given.

Options:
  --context CONTEXT   kube context of the environment (required; the current
                      context is never used)
  --namespace NS      namespace (default: podiumd)
  --dry-run           show what --apply would do, write nothing (default)
  --apply             create the missing tokens in objecten
  --configmap NAME    objecttypen's setup-configuration ConfigMap (default:
                      objecttypen-configuration, else the only ConfigMap named
                      *objecttypen*-configuration)
  -h, --help          show this help
EOF
}

while [ $# -gt 0 ]; do
  case "${1}" in
    --context) CONTEXT="${2:?--context needs a value}"; shift 2 ;;
    --namespace|-n) NAMESPACE="${2:?--namespace needs a value}"; shift 2 ;;
    --dry-run) APPLY=false; shift ;;
    --apply) APPLY=true; shift ;;
    --configmap) CONFIGMAP="${2:?--configmap needs a value}"; shift 2 ;;
    -h|--help) print_usage; exit 0 ;;
    *) echo "Unknown argument: ${1}" >&2; print_usage >&2; exit 2 ;;
  esac
done

if [ -z "${CONTEXT}" ]; then
  echo "ERROR: --context is required" >&2
  print_usage >&2
  exit 2
fi

k() {
  kubectl --context "${CONTEXT}" --namespace "${NAMESPACE}" "$@"
}

for deploy in "${OBJECTTYPEN_DEPLOY}" "${OBJECTEN_DEPLOY}"; do
  if ! k get deploy "${deploy}" -o name >/dev/null 2>&1; then
    echo "ERROR: deployment ${deploy} not found in ${CONTEXT}/${NAMESPACE}." >&2
    echo "Run this before the 4.10.0 upgrade, while objecttypen and objecten both run." >&2
    exit 1
  fi
done

if [ -z "${CONFIGMAP}" ]; then
  if k get configmap objecttypen-configuration -o name >/dev/null 2>&1; then
    CONFIGMAP="objecttypen-configuration"
  else
    candidates="$(k get configmap -o name | sed -n 's|^configmap/\(.*objecttypen.*-configuration\)$|\1|p')"
    if [ "$(printf '%s' "${candidates}" | grep -c .)" -ne 1 ]; then
      echo "ERROR: cannot find objecttypen's setup-configuration ConfigMap (found: ${candidates:-none})." >&2
      echo "Pass it with --configmap NAME." >&2
      exit 1
    fi
    CONFIGMAP="${candidates}"
  fi
fi

# Runs in the objecttypen pod. stdin: objecttypen's configuration.yaml.
# stdout: one marker line with the configured identifiers and all tokens.
read -r -d '' EXPORT_PY <<'PY' || true
import json
import sys

import yaml
from django.apps import apps

cfg = yaml.safe_load(sys.stdin.read() or "") or {}
items = ((cfg.get("tokenauth") or {}).get("items") or []) if isinstance(cfg, dict) else []
configured = sorted({str(i["identifier"]) for i in items if isinstance(i, dict) and i.get("identifier")})
models = [m for m in apps.get_models() if m.__name__ == "TokenAuth"]
if len(models) != 1:
    raise SystemExit("expected one TokenAuth model, found %d" % len(models))
fields = ("identifier", "token", "contact_person", "email", "organization", "application", "administration")
rows = [dict(zip(fields, r, strict=True)) for r in models[0].objects.order_by("identifier").values_list(*fields)]
print("OBJECTTYPEN-TOKENS " + json.dumps({"configured": configured, "tokens": rows}))
PY

# Runs in the objecten pod. stdin: the export above. Prints identifiers and
# sha256 prefixes only.
read -r -d '' IMPORT_PY <<'PY' || true
import hashlib
import json
import sys

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import transaction

APPLY = __APPLY__  # set by the shell script
SUFFIX = "-objecttypen"
data = None
for line in sys.stdin:
    if line.startswith("OBJECTTYPEN-TOKENS "):
        data = json.loads(line[len("OBJECTTYPEN-TOKENS "):])
if data is None:
    raise SystemExit("ERROR: no token export received from objecttypen")
models = [m for m in apps.get_models() if m.__name__ == "TokenAuth"]
if len(models) != 1:
    raise SystemExit("expected one TokenAuth model, found %d" % len(models))
T = models[0]
max_len = T._meta.get_field("identifier").max_length
by_token = dict(T.objects.values_list("token", "identifier"))
configured = set(data["configured"])
taken = set(T.objects.values_list("identifier", flat=True)) | configured | {c + SUFFIX for c in configured}
counts = {}
create = []
print("Mode: %s" % ("apply" if APPLY else "dry-run (nothing written; --apply creates the tokens)"))
print("%-32s %-12s %-19s %s" % ("objecttypen identifier", "sha256", "action", "objecten identifier"))
for row in data["tokens"]:
    ident, token = row["identifier"], row["token"]
    digest = hashlib.sha256(token.encode()).hexdigest()[:12]
    if token in by_token:
        action, target = "exists-same-token", by_token[token]
    elif ident in configured:
        action, target = "skipped", "- (in objecttypen configuration: merged by the values migration)"
    else:
        target, n = ident, 1
        while target in taken:
            tail = SUFFIX if n == 1 else "%s-%d" % (SUFFIX, n)
            target, n = ident[: max_len - len(tail)] + tail, n + 1
        action = "created" if target == ident else "created-as-renamed"
        new = T(identifier=target, token=token, is_superuser=False,
                **{f: row[f] or "" for f in ("contact_person", "email", "organization",
                                             "application", "administration")})
        try:
            new.full_clean()
        except ValidationError as e:
            action, target = "error", "%s (invalid: %s)" % (target, ", ".join(sorted(e.message_dict)))
        else:
            create.append(new)
            taken.add(target)
            by_token[token] = target
    counts[action] = counts.get(action, 0) + 1
    print("%-32s %-12s %-19s %s" % (ident, digest, action, target))
print("Summary: " + (", ".join("%s %d" % kv for kv in sorted(counts.items())) or "no objecttypen tokens"))
if counts.get("error"):
    raise SystemExit("ERROR: %d token(s) cannot be created as listed above; nothing written. "
                     "Fix them in objecttypen or add them to objecten by hand." % counts["error"])
if APPLY:
    with transaction.atomic():
        for new in create:
            new.save()
    print("Created %d token(s) in objecten." % len(create))
elif create:
    print("Dry-run: run again with --apply to create %d token(s)." % len(create))
PY

if [ "${APPLY}" = true ]; then
  IMPORT_PY="${IMPORT_PY/__APPLY__/True}"
else
  IMPORT_PY="${IMPORT_PY/__APPLY__/False}"
fi

echo "Context ${CONTEXT}, namespace ${NAMESPACE}, objecttypen configuration from ConfigMap ${CONFIGMAP}"
k get configmap "${CONFIGMAP}" -o jsonpath='{.data.configuration\.yaml}' \
  | k exec -i "deploy/${OBJECTTYPEN_DEPLOY}" -c objecttypen -- \
      python /app/src/manage.py shell --verbosity 0 -c "${EXPORT_PY}" \
  | k exec -i "deploy/${OBJECTEN_DEPLOY}" -c objecten -- \
      python /app/src/manage.py shell --verbosity 0 -c "${IMPORT_PY}"
