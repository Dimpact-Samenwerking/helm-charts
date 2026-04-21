#!/usr/bin/env bash
# migrate-prometheus-to-kube-prometheus-stack.sh
#
# Migration helper: converts a monitoring-logging environment values file from
# the old prometheus-community/prometheus chart layout to the new
# kube-prometheus-stack layout used in monitoring-logging 1.0.11+.
#
# The script applies all mechanical substitutions (key renames, service URL
# updates) to a copy of your values file and prints a diff. Items that require
# structural YAML changes (storageSpec, pushgateway) are flagged as warnings
# for manual follow-up.
#
# Usage:
#   ./migrate-prometheus-to-kube-prometheus-stack.sh <input-file> [output-file]
#
# Examples:
#   ./migrate-prometheus-to-kube-prometheus-stack.sh values-monitoring-prod.yaml
#   ./migrate-prometheus-to-kube-prometheus-stack.sh values-monitoring-prod.yaml values-monitoring-prod-new.yaml
#
# Key mapping applied automatically:
#
#   OLD (prometheus-community/prometheus)          NEW (kube-prometheus-stack)
#   ─────────────────────────────────────────────────────────────────────────
#   prometheus:                                    kube-prometheus-stack:
#   prometheus.server.extraFlags:                  .prometheus.prometheusSpec.additionalArgs:
#     - web.enable-remote-write-receiver             - name: web.enable-remote-write-receiver
#                                                      value: ""
#   prometheus.configmapReload.prometheus:         .prometheusOperator.prometheusConfigReloader:
#   <release>-prometheus-server                    <release>-kube-prometheus-stack-prometheus:9090
#   prometheus-server/api/v1/write                 kube-prometheus-stack-prometheus:9090/api/v1/write
#
# Items requiring MANUAL migration (flagged as warnings):
#   prometheus.server.persistentVolume.*  →  storageSpec.volumeClaimTemplate.spec.*
#   prometheus.prometheus-pushgateway.*   →  top-level prometheus-pushgateway: key
#
# Requirements: bash, sed, grep, diff (or git for coloured diff)

set -euo pipefail

# --- Args ---------------------------------------------------------------------
if [[ $# -lt 1 ]]; then
  sed -n '/^# Usage:/,/^# Requirements/{ /^# Requirements/d; s/^# \{0,2\}//; p }' "$0"
  exit 1
fi

INPUT="$1"
if [[ ! -f "$INPUT" ]]; then
  echo "ERROR: file not found: $INPUT" >&2
  exit 1
fi

if [[ $# -ge 2 ]]; then
  OUTPUT="$2"
else
  BASE="${INPUT%.*}"
  EXT="${INPUT##*.}"
  OUTPUT="${BASE}-migrated.${EXT}"
fi

cp "$INPUT" "$OUTPUT"

echo "Input : $INPUT"
echo "Output: $OUTPUT"
echo ""

# --- Helper -------------------------------------------------------------------
CHANGES=0
apply() {
  local description="$1"
  local old="$2"
  local new="$3"
  local count
  count=$(grep -cF "$old" "$OUTPUT" || true)
  if [[ "$count" -gt 0 ]]; then
    sed -i "s|${old}|${new}|g" "$OUTPUT"
    printf "  [%2dx] %s\n" "$count" "$description"
    CHANGES=$(( CHANGES + count ))
  fi
}

echo "==> Applying substitutions..."

# 1. Top-level prometheus: → kube-prometheus-stack:
#    Only the unindented key (start of line).
if grep -qP '^prometheus:' "$OUTPUT"; then
  sed -i 's/^prometheus:/kube-prometheus-stack:/' "$OUTPUT"
  echo "  [ 1x] prometheus: → kube-prometheus-stack:  (top-level key)"
  CHANGES=$(( CHANGES + 1 ))
fi

# 2. extraFlags block → additionalArgs
#    Pattern:
#      extraFlags:
#        - web.enable-remote-write-receiver
#    →
#      additionalArgs:
#        - name: web.enable-remote-write-receiver
#          value: ""
if grep -q 'extraFlags:' "$OUTPUT"; then
  # Use Python for multi-line replacement (sed -i multiline is not portable)
  python3 - "$OUTPUT" <<'PYEOF'
import re, sys
path = sys.argv[1]
text = open(path).read()
pattern = re.compile(
    r'( *)extraFlags:\n(\s*)- web\.enable-remote-write-receiver\n',
    re.MULTILINE
)
def replace(m):
    indent = m.group(1)
    return (
        f"{indent}additionalArgs:\n"
        f"{indent}  - name: web.enable-remote-write-receiver\n"
        f"{indent}    value: \"\"\n"
    )
new_text, n = pattern.subn(replace, text)
if n:
    open(path, 'w').write(new_text)
    print(f"  [ {n}x] extraFlags → additionalArgs  (web.enable-remote-write-receiver)")
PYEOF
fi

# 3. configmapReload: → prometheusOperator:
apply "configmapReload: → prometheusOperator:" \
  "configmapReload:" "prometheusOperator:"

# 4. Grafana datasource / any URL referencing the old prometheus service name
apply "Grafana datasource URL: -prometheus-server → -kube-prometheus-stack-prometheus:9090" \
  "-prometheus-server" "-kube-prometheus-stack-prometheus:9090"

# 5. OTel remote-write endpoint (catches the /api/v1/write path variant)
apply "OTel endpoint: prometheus-server/api/v1/write → kube-prometheus-stack-prometheus:9090/api/v1/write" \
  "prometheus-server/api/v1/write" \
  "kube-prometheus-stack-prometheus:9090/api/v1/write"
# (already covered by step 4 for the hostname part, but guard against partial overlaps)

echo ""
echo "  Total substitutions applied: $CHANGES"

# --- Manual-review warnings ---------------------------------------------------
WARNINGS=0
warn() {
  echo ""
  echo "  [WARN] $1"
  WARNINGS=$(( WARNINGS + 1 ))
}

echo ""
echo "==> Checking for items that require manual migration..."

if grep -q 'persistentVolume:' "$OUTPUT"; then
  warn "persistentVolume: found — migrate to storageSpec:"
  cat <<'EOF'
         OLD (under prometheus.server):
           persistentVolume:
             enabled: true
             storageClass: managed-csi
             size: 20Gi
             accessModes: ["ReadWriteOnce"]

         NEW (under kube-prometheus-stack.prometheus.prometheusSpec):
           storageSpec:
             volumeClaimTemplate:
               spec:
                 storageClassName: managed-csi
                 accessModes: ["ReadWriteOnce"]
                 resources:
                   requests:
                     storage: 20Gi
EOF
fi

if grep -q 'prometheus-pushgateway:' "$OUTPUT"; then
  warn "prometheus-pushgateway: found inside kube-prometheus-stack block."
  cat <<'EOF'
         kube-prometheus-stack does not bundle pushgateway.
         Move it to a top-level key (no indentation) in your values file:

           prometheus-pushgateway:
             enabled: true
             nodeSelector: ...
             resources: ...
             image:
               repository: quay.io/prometheus/pushgateway
               tag: v1.11.1
EOF
fi

if grep -q 'kubeRBACProxy:' "$OUTPUT"; then
  warn "kubeRBACProxy: found — this key is no longer used in kube-prometheus-stack."
  echo "         The kube-rbac-proxy is managed by the operator; remove this block."
fi

if grep -q 'extraScrapeConfigs:' "$OUTPUT"; then
  warn "extraScrapeConfigs: found — rename to additionalScrapeConfigs: under prometheusSpec."
fi

if [[ "$WARNINGS" -eq 0 ]]; then
  echo "  None found."
fi

# --- Diff ---------------------------------------------------------------------
echo ""
echo "==> Diff ($INPUT → $OUTPUT):"
echo "────────────────────────────────────────────────────────────────"
if command -v git &>/dev/null; then
  git diff --no-index --unified=3 -- "$INPUT" "$OUTPUT" || true
else
  diff --unified=3 "$INPUT" "$OUTPUT" || true
fi
echo "────────────────────────────────────────────────────────────────"

# --- Next steps ---------------------------------------------------------------
echo ""
echo "NEXT STEPS:"
echo "  1. Review $OUTPUT carefully."
if [[ "$WARNINGS" -gt 0 ]]; then
  echo "  2. Address the $WARNINGS manual migration warning(s) above."
  echo "  3. Delete the old 'prometheus:' block once migration is verified."
  echo "  4. Install CRDs:  ./scripts/install-prometheus-operator-crds.sh --context <cluster>"
  echo "  5. Validate:      helm template monitoring charts/monitoring-logging \\"
  echo "                      -f $OUTPUT -n monitoring"
else
  echo "  2. Delete the old 'prometheus:' block once migration is verified."
  echo "  3. Install CRDs:  ./scripts/install-prometheus-operator-crds.sh --context <cluster>"
  echo "  4. Validate:      helm template monitoring charts/monitoring-logging \\"
  echo "                      -f $OUTPUT -n monitoring"
fi
