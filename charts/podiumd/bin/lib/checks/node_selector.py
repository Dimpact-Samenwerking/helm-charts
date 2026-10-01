"""Verify every own workload template exposes a `nodeSelector` field.

aks-blue requires `nodeSelector: kubernetes.azure.com/mode: user` on all app
workloads; a template without the field can't be fixed by env values.

Scans raw template source (Go templating breaks a YAML parser), split on `---`, so it
only confirms a `nodeSelector:` key exists in the document. A chunk that `include`s
a same-file `define` block (e.g. pabc-seed-job.yaml's pod template) is credited with
that block's text, since a define emits nothing where it is written. Only plain
`include "X"` of a same-file define counts; `include (print ...)` never matches.
"""

import re

from collections.abc import Iterator
from pathlib import Path

WORKLOAD_KIND_RE = re.compile(r"^kind:\s*(Deployment|StatefulSet|DaemonSet|Job|CronJob)\s*$", re.MULTILINE)
NAME_RE = re.compile(r"^\s*name:\s*(.+)$", re.MULTILINE)
NODE_SELECTOR_RE = re.compile(r"\bnodeSelector\s*:")
DOC_SPLIT_RE = re.compile(r"(?m)^---\s*$")
DEFINE_BLOCK_RE = re.compile(
    r'\{\{-?\s*define\s+"(?P<name>[^"]+)"\s*-?\}\}(?P<body>.*?)\{\{-?\s*end\s*-?\}\}', re.DOTALL
)
INCLUDE_CALL_RE = re.compile(r'include\s+"(?P<name>[^"]+)"')


def _referenced_define_bodies(doc: str, define_bodies: dict[str, str]):
    """Bodies of same-file define blocks this chunk calls via a plain `include "X"`."""
    return [define_bodies[m.group("name")] for m in INCLUDE_CALL_RE.finditer(doc) if m.group("name") in define_bodies]


def file_define_bodies(text: str) -> dict[str, str]:
    """{name: body} for every `{{ define "X" }}...{{ end }}` block in the text."""
    return {m.group("name"): m.group("body") for m in DEFINE_BLOCK_RE.finditer(text)}


def missing_node_selector(doc: str, define_bodies: dict[str, str]) -> tuple[str, str] | None:
    """(kind, name) when doc is a workload with no nodeSelector (own text or included
    same-file defines), else None. Shared by check_node_selector and fix-node-selector."""
    kind_m = WORKLOAD_KIND_RE.search(doc)
    if not kind_m or NODE_SELECTOR_RE.search(doc):
        return None
    if any(NODE_SELECTOR_RE.search(body) for body in _referenced_define_bodies(doc, define_bodies)):
        return None
    name_m = NAME_RE.search(doc)
    return kind_m.group(1), (name_m.group(1).strip() if name_m else "(unknown name)")


def template_texts(templates_dir: Path) -> Iterator[tuple[Path, str]]:
    """(path, text) of every templates/**/*.yaml, in path order."""
    for path in sorted(templates_dir.rglob("*.yaml")):
        if path.is_file():
            yield path, path.read_text(encoding="utf-8")


def scan_missing_node_selector(templates_dir: Path) -> list[tuple[Path, str, str]]:
    """(path, kind, name) for every workload in templates/*.yaml missing nodeSelector."""
    findings: list[tuple[Path, str, str]] = []
    for path, text in template_texts(templates_dir):
        define_bodies = file_define_bodies(text)
        for doc in DOC_SPLIT_RE.split(text):
            missing = missing_node_selector(doc, define_bodies)
            if missing is not None:
                findings.append((path, *missing))
    return findings


def check_node_selector(chart_dir: Path):
    """Fail if any own workload template lacks a nodeSelector field, listing each."""
    findings = scan_missing_node_selector(chart_dir / "templates")

    if not findings:
        print("OK: every Deployment/StatefulSet/DaemonSet/Job/CronJob in templates/*.yaml exposes a nodeSelector field")
        return True, "0 violation(s)"

    print(
        f"Found {len(findings)} workload template(s) with no nodeSelector field "
        f'(.github/copilot-instructions.md "AKS-Blue Cluster Conventions"):'
    )
    for path, kind, name in findings:
        rel = path.relative_to(chart_dir)
        print(f"  {rel}  {kind}/{name}")

    return False, f"{len(findings)} violation(s)"
