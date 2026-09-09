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
sub-chart's.

A doc-split chunk that builds its own pod spec by INCLUDING a same-file
`{{- define "X" -}} ... {{- end }}` block (real case: pabc-seed-job.yaml's
own "podiumd.pabcSeedJob.podTemplate", defined once so its rendered text
can also feed the Job name's checksum — see that file's own comment) is
credited with whatever that referenced block's own text contains too: a
`define` block emits nothing at its own physical location, so its
`nodeSelector:` conditional can sit in a doc-split chunk entirely
different from (often physically BEFORE) the one with the resource's own
"kind: Job" line — the exact split a bare per-chunk scan can't see across.
Only ever resolved for a `define` block in the SAME file, and only when
the chunk's own text calls it via a plain `include "X"` (a literal quoted
name — `include (print ...)`, as keycloak-import-podiumd-realm-job.yaml's
own unrelated same-file include call does, never matches, so it can't be
mistaken for one of these); a shared helper template like "podiumd.image"
or "podiumd.labels" defined in this chart's own _helpers.tpl is a
different file and never appears in a file's own local defines either
way, so crediting it here was never a risk to begin with."""
import re

WORKLOAD_KIND_RE = re.compile(r"^kind:\s*(Deployment|StatefulSet|DaemonSet|Job|CronJob)\s*$", re.MULTILINE)
NAME_RE = re.compile(r"^\s*name:\s*(.+)$", re.MULTILINE)
NODE_SELECTOR_RE = re.compile(r"\bnodeSelector\s*:")
DOC_SPLIT_RE = re.compile(r"(?m)^---\s*$")
DEFINE_BLOCK_RE = re.compile(r'\{\{-?\s*define\s+"(?P<name>[^"]+)"\s*-?\}\}(?P<body>.*?)\{\{-?\s*end\s*-?\}\}',
                              re.DOTALL)
INCLUDE_CALL_RE = re.compile(r'include\s+"(?P<name>[^"]+)"')


def _referenced_define_bodies(doc, define_bodies):
    """[body, ...] for every same-file `{{ define "X" }}...{{ end }}` block
    (define_bodies, keyed by name — see DEFINE_BLOCK_RE) this doc chunk's
    own text calls via a plain `include "X"` — see module docstring for
    why a doc that only includes its pod spec from such a block needs
    that block's own text considered part of its document too."""
    return [define_bodies[m.group("name")] for m in INCLUDE_CALL_RE.finditer(doc)
            if m.group("name") in define_bodies]


def scan_missing_node_selector(templates_dir):
    """Returns a list of (path, kind, name) for every workload resource in
    templates/*.yaml with no nodeSelector field anywhere in its document
    (including, per _referenced_define_bodies, any same-file `define`
    block it includes its pod spec from)."""
    findings = []
    for path in sorted(templates_dir.rglob("*.yaml")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        define_bodies = {m.group("name"): m.group("body") for m in DEFINE_BLOCK_RE.finditer(text)}
        for doc in DOC_SPLIT_RE.split(text):
            kind_m = WORKLOAD_KIND_RE.search(doc)
            if not kind_m:
                continue
            if NODE_SELECTOR_RE.search(doc):
                continue
            if any(NODE_SELECTOR_RE.search(body) for body in _referenced_define_bodies(doc, define_bodies)):
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
