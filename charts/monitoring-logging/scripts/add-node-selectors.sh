#!/usr/bin/env bash
# add-node-selectors.sh
#
# Adds a nodeSelector to every monitoring-logging component in an environment
# values file, but only when no nodeSelector is already present for that component.
#
# Usage:
#   ./add-node-selectors.sh <values-file> [--key <label-key>] [--value <label-value>] [--dry-run]
#
# Defaults:
#   --key   kubernetes.azure.com/agentpool  (AKS node pool label)
#   --value userpool
#
# Examples:
#   ./add-node-selectors.sh values-monitoring-prod.yaml
#   ./add-node-selectors.sh values-monitoring-prod.yaml --key kubernetes.io/hostname --value mynode
#   ./add-node-selectors.sh values-monitoring-prod.yaml --dry-run

set -euo pipefail

usage() {
  grep '^#' "$0" | sed 's/^# \{0,1\}//'
  exit 1
}

VALUES_FILE=""
SELECTOR_KEY="kubernetes.azure.com/agentpool"
SELECTOR_VALUE="userpool"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --key)    SELECTOR_KEY="$2";   shift 2 ;;
    --value)  SELECTOR_VALUE="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true;        shift   ;;
    -h|--help) usage ;;
    *)
      if [[ -z "$VALUES_FILE" ]]; then
        VALUES_FILE="$1"; shift
      else
        echo "Unknown argument: $1" >&2; usage
      fi
      ;;
  esac
done

if [[ -z "$VALUES_FILE" ]]; then
  echo "ERROR: No values file specified." >&2
  usage
fi

if [[ ! -f "$VALUES_FILE" ]]; then
  echo "ERROR: File not found: $VALUES_FILE" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Components and the YAML path where nodeSelector belongs.
# Format: "top_level_key  yaml_path_prefix  indent_spaces"
# The script inserts:
#   <indent>nodeSelector:
#   <indent>  <key>: <value>
# immediately after the first line that matches the anchor pattern.
# ---------------------------------------------------------------------------
# We use Python for the actual YAML patching to handle indentation correctly.
# ---------------------------------------------------------------------------

python3 - "$VALUES_FILE" "$SELECTOR_KEY" "$SELECTOR_VALUE" "$DRY_RUN" <<'PYEOF'
import sys, re

values_file  = sys.argv[1]
sel_key      = sys.argv[2]
sel_val      = sys.argv[3]
dry_run      = sys.argv[4].lower() == "true"

# Each entry: (description, regex that matches the component's top-level or section key line,
#              expected indent of that key line)
# The nodeSelector will be inserted as a sibling key at the same indent + 2.
COMPONENTS = [
    # (label, pattern to find the section opener, indent of that opener line)
    ("grafana",
     r'^grafana:$', 0),
    ("kube-prometheus-stack › prometheus › prometheusSpec",
     r'^\s{6}prometheusSpec:$', 6),
    ("kube-prometheus-stack › prometheusOperator",
     r'^\s{2}prometheusOperator:$', 2),
    # admissionWebhooks.patch is a Job (certgen) that runs at install/upgrade time
    ("kube-prometheus-stack › prometheusOperator › admissionWebhooks › patch",
     r'^\s{6}patch:$', 6),
    ("kube-prometheus-stack › prometheus-node-exporter",
     r'^\s{2}prometheus-node-exporter:$', 2),
    ("kube-prometheus-stack › kube-state-metrics",
     r'^\s{2}kube-state-metrics:$', 2),
    # alertmanager is disabled by default; included so it is set correctly if enabled
    ("kube-prometheus-stack › alertmanager › alertmanagerSpec (disabled by default)",
     r'^\s{4}alertmanagerSpec:$', 4),
    ("prometheus-pushgateway",
     r'^prometheus-pushgateway:$', 0),
    ("alloy",
     r'^alloy:$', 0),
    ("loki › resultsCache",
     r'^\s{4}resultsCache:$', 4),
    ("loki › chunksCache",
     r'^\s{4}chunksCache:$', 4),
    ("loki › indexGateway",
     r'^\s{4}indexGateway:$', 4),
    ("loki › queryScheduler",
     r'^\s{4}queryScheduler:$', 4),
    ("loki › queryFrontend",
     r'^\s{4}queryFrontend:$', 4),
    ("loki › distributor",
     r'^\s{4}distributor:$', 4),
    ("loki › querier",
     r'^\s{4}querier:$', 4),
    ("loki › gateway",
     r'^\s{4}gateway:$', 4),
    ("loki › ingester",
     r'^\s{4}ingester:$', 4),
    ("loki › ingester › zoneA",
     r'^\s{8}zoneA:', 8),
    ("loki › ingester › zoneB",
     r'^\s{8}zoneB:', 8),
    ("loki › ingester › zoneC",
     r'^\s{8}zoneC:', 8),
    ("loki › compactor",
     r'^\s{4}compactor:$', 4),
    ("loki › minio",
     r'^\s{4}minio:$', 4),
    ("tempo",
     r'^tempo:$', 0),
    ("opentelemetry-collector",
     r'^opentelemetry-collector:$', 0),
]

with open(values_file, encoding='utf-8') as f:
    lines = f.readlines()

insertions = []  # list of (after_line_index, indent, label)

def has_node_selector_in_block(lines, start, block_indent):
    """Return True if a nodeSelector key exists within the block starting at `start`."""
    for i in range(start + 1, len(lines)):
        l = lines[i]
        stripped = l.rstrip()
        if stripped == '':
            continue
        cur_indent = len(l) - len(l.lstrip())
        if cur_indent <= block_indent:
            break  # left the block
        if re.match(r'\s*nodeSelector\s*:', l):
            return True
    return False

def find_insert_point(lines, start, block_indent):
    """
    Find the line index after which to insert the nodeSelector.
    We want to insert it as the first key in the block (right after the opener line),
    but after any inline value on the opener line.
    Returns the index of the opener line itself (insert after it).
    """
    return start

for label, pattern, opener_indent in COMPONENTS:
    found = False
    for i, line in enumerate(lines):
        if re.match(pattern, line.rstrip()):
            found = True
            if has_node_selector_in_block(lines, i, opener_indent):
                print(f"  SKIP  {label}: nodeSelector already present")
            else:
                insertions.append((i, opener_indent + 2, label))
                print(f"  ADD   {label}")
            break
    if not found:
        print(f"  MISS  {label}: section not found in file (skipping)")

if not insertions:
    print("\nNothing to do.")
    sys.exit(0)

# Apply insertions in reverse order so line numbers stay valid
insertions.sort(key=lambda x: x[0], reverse=True)

for after_idx, indent, label in insertions:
    ns_lines = [
        ' ' * indent + 'nodeSelector:\n',
        ' ' * indent + f'  {sel_key}: {sel_val}\n',
    ]
    lines = lines[:after_idx + 1] + ns_lines + lines[after_idx + 1:]

if dry_run:
    print(f"\n[DRY RUN] Would write {len(insertions)} nodeSelector(s) to {values_file}")
    print("Use --dry-run=false or omit --dry-run to apply.")
else:
    with open(values_file, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print(f"\nWrote {len(insertions)} nodeSelector(s) to {values_file}")
PYEOF
