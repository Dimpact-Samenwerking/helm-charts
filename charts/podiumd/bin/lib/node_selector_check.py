"""Verifies every workload template (Deployment/StatefulSet/DaemonSet/
Job/CronJob) in this chart's OWN templates/*.yaml exposes a `nodeSelector`
field somewhere in its pod spec, per .github/copilot-instructions.md's
AKS-Blue convention: "All workloads on aks-blue require
`nodeSelector: kubernetes.azure.com/mode: user` — ... all app workloads."
A template with no nodeSelector field at all can never be made compliant
by an env-values override, no matter what that environment sets.

Scans the raw template source (not a `helm template` render) by splitting
each file on its bare `---` document separators and checking each
resulting document independently — Go template syntax breaks a real YAML
parser, so this is a best-effort textual scan, not a structural one: it
only confirms a `nodeSelector:` key exists somewhere in the resource's
document, not that it's wired to the pod spec exactly where Kubernetes
expects it. Only ever covers this chart's own templates, never a vendored
sub-chart's."""
import re

WORKLOAD_KIND_RE = re.compile(r"^kind:\s*(Deployment|StatefulSet|DaemonSet|Job|CronJob)\s*$", re.MULTILINE)
NAME_RE = re.compile(r"^\s*name:\s*(.+)$", re.MULTILINE)
NODE_SELECTOR_RE = re.compile(r"\bnodeSelector\s*:")
DOC_SPLIT_RE = re.compile(r"(?m)^---\s*$")


def scan_missing_node_selector(templates_dir):
    """Returns a list of (path, kind, name) for every workload resource in
    templates/*.yaml with no nodeSelector field anywhere in its document."""
    findings = []
    for path in sorted(templates_dir.rglob("*.yaml")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for doc in DOC_SPLIT_RE.split(text):
            kind_m = WORKLOAD_KIND_RE.search(doc)
            if not kind_m:
                continue
            if NODE_SELECTOR_RE.search(doc):
                continue
            name_m = NAME_RE.search(doc)
            name = name_m.group(1).strip() if name_m else "(unknown name)"
            findings.append((path, kind_m.group(1), name))
    return findings


def check_node_selector(chart_dir):
    findings = scan_missing_node_selector(chart_dir / "templates")

    if not findings:
        print("OK: every Deployment/StatefulSet/DaemonSet/Job/CronJob in templates/*.yaml "
              "exposes a nodeSelector field")
        return True, "0 violation(s)"

    print(f"Found {len(findings)} workload template(s) with no nodeSelector field "
          f'(.github/copilot-instructions.md "AKS-Blue Cluster Conventions"):')
    for path, kind, name in findings:
        rel = path.relative_to(chart_dir)
        print(f"  {rel}  {kind}/{name}")

    return False, f"{len(findings)} violation(s)"
