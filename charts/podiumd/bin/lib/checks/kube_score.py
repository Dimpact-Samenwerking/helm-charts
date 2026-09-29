"""Check every rendered container declares CPU/memory requests and limits.

This is the repo convention from .github/copilot-instructions.md, enforced via
quality_gates.kube_score_check_id, not kube-score's full opinion set.
"""

import json
import shutil

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import NotRequired
from typing import TypedDict
from typing import TypeGuard

from lib.procutil import run
from lib.render_scope import OWN_TEMPLATES_PREFIX
from lib.render_scope import ResourceLocations
from lib.render_scope import chart_name_from_source
from lib.render_scope import friendly_vendor_charts
from lib.render_scope import print_grouped_findings
from lib.render_scope import render_chart_docs
from lib.render_scope import resource_line
from lib.render_scope import scan_outcome
from lib.settings import quality_gates_kube_score_check_id
from lib.yaml_types import shape_problem

# A finding as (object_name, container, summary); a vendored one is
# prefixed with its sub-chart: (chart, object_name, container, summary).
KubeScoreFinding = tuple[str, str, str]
VendoredKubeScoreFinding = tuple[str, str, str, str]


class KubeScoreComment(TypedDict):
    """One comment of a kube-score check (the fields this module reads)."""

    path: NotRequired[str]
    summary: NotRequired[str]


class KubeScoreCheckInfo(TypedDict):
    """The "check" identity of one kube-score check result."""

    id: str


class KubeScoreCheck(TypedDict):
    """One check result for a scored object."""

    check: KubeScoreCheckInfo
    grade: int
    skipped: NotRequired[bool]
    comments: NotRequired[list[KubeScoreComment] | None]


class KubeScoreObject(TypedDict):
    """One object in kube-score's JSON output (only the fields read here)."""

    object_name: NotRequired[str]
    checks: NotRequired[list[KubeScoreCheck]]


_OBJECT_LIST_SHAPE = [
    {
        "object_name?": str,
        "checks?": [
            {
                "check": {"id": str},
                "grade": int,
                "skipped?": bool,
                "comments?": ([{"path?": str, "summary?": str}], type(None)),
            }
        ],
    }
]


def is_kube_score_objects(value: object) -> TypeGuard[list[KubeScoreObject]]:
    """Whether parsed kube-score JSON is a list of KubeScoreObject."""
    return shape_problem(value, _OBJECT_LIST_SHAPE) is None


def run_kube_score(yaml_text: str) -> list[KubeScoreObject] | None:
    """Parsed kube-score JSON for a YAML stream, or None if unparseable.

    kube-score prints "null" for a stream with no scoreable objects (e.g. CRD-only
    charts); that is normalized to [] so it doesn't look like a crash.
    """
    result = run(["kube-score", "score", "-o", "json", "-"], input=yaml_text, capture_output=True, text=True)
    try:
        data: object = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if data is None:
        return []
    return data if is_kube_score_objects(data) else None


def extract_resource_findings(
    kube_score_objects: list[KubeScoreObject] | None, check_id: str
) -> list[KubeScoreFinding]:
    """Every non-skipped, below-full-grade `check_id` finding as (object_name, container, summary)."""
    findings: list[KubeScoreFinding] = []
    for obj in kube_score_objects or []:
        object_name = obj.get("object_name", "?")
        for c in obj.get("checks", []):
            if c["check"]["id"] != check_id or c.get("skipped") or c["grade"] >= 10:
                continue
            findings.extend(
                (object_name, comment.get("path", ""), comment.get("summary", ""))
                for comment in c.get("comments") or []
            )
    return findings


def parse_kube_score_object_name(object_name: str):
    """ "Kind/apiVersion/namespace/name" -> (kind, namespace, name), or (None, None, None).

    Split from both ends because apiVersion itself can contain "/" (e.g. "batch/v1").
    """
    parts = object_name.split("/")
    if len(parts) < 4:
        return None, None, None
    return parts[0], parts[-2], parts[-1]


def _kube_score_line_suffix(object_name: str, locations: ResourceLocations):
    kind, namespace, name = parse_kube_score_object_name(object_name)
    if not kind:
        return ""
    line = resource_line(locations, kind, name, namespace=namespace)
    return f" — rendered line {line}" if line else ""


@dataclass
class KubeScoreResult:
    """A completed render+score pass: rendered-line locations and the three finding buckets."""

    locations: ResourceLocations
    own_real: list[KubeScoreFinding]
    vendored_partner: list[VendoredKubeScoreFinding]
    vendored_other: list[VendoredKubeScoreFinding]


def _score_vendored_charts(docs: list[tuple[str, str]], check_id: str, vendor_map: dict[str, str]):
    """Score each vendored sub-chart separately and split findings into (partner, other).

    kube-score's JSON has no source info, hence one run per sub-chart. Returns
    (None, None, error) on unparseable output.
    """
    vendored_by_chart_docs: dict[str, list[str]] = {}
    for source, text in docs:
        if not source.startswith(OWN_TEMPLATES_PREFIX):
            vendored_by_chart_docs.setdefault(chart_name_from_source(source), []).append(text)

    vendored_partner: list[VendoredKubeScoreFinding] = []
    vendored_other: list[VendoredKubeScoreFinding] = []
    for chart, texts in vendored_by_chart_docs.items():
        objects = run_kube_score("".join(texts))
        if objects is None:
            return None, None, "kube-score produced unparseable output"
        bucket = vendored_partner if chart in vendor_map else vendored_other
        for object_name, container, summary in extract_resource_findings(objects, check_id):
            bucket.append((chart, object_name, container, summary))
    return vendored_partner, vendored_other, None


def _score_rendered_chart(chart_dir: Path, extra_args: list[str], check_id: str):
    """(KubeScoreResult, None) for the rendered chart, or (None, error) on any failure."""
    rendered, error = render_chart_docs(chart_dir, extra_args)
    if rendered is None:
        return None, error
    locations, docs = rendered.locations, rendered.docs
    own_text = "".join(text for source, text in docs if source.startswith(OWN_TEMPLATES_PREFIX))
    own_objects = run_kube_score(own_text)
    if own_objects is None:
        return None, "kube-score produced unparseable output"
    own_real = extract_resource_findings(own_objects, check_id)

    vendor_map = friendly_vendor_charts(chart_dir)
    vendored_partner, vendored_other, error = _score_vendored_charts(docs, check_id, vendor_map)
    if vendored_partner is None or vendored_other is None:
        return None, error

    return KubeScoreResult(locations, own_real, vendored_partner, vendored_other), None


def _print_kube_score_findings(scored: KubeScoreResult):
    """Print the own/partner-vendor/other-vendor sections for `result`."""
    if scored.own_real:
        print(
            f"Found {len(scored.own_real)} real kube-score issue(s) in this chart's own templates "
            f"(missing resources.requests/.limits — required by "
            f".github/copilot-instructions.md — these fail the check):"
        )
        print_grouped_findings(
            scored.own_real,
            key_fn=lambda f: (f[0], f[1]),
            item_fn=lambda f: f[2],
            label_fn=lambda k: f"{k[0]} ({k[1]}){_kube_score_line_suffix(k[0], scored.locations)}",
            items_label="issue(s)",
        )
        print()

    if scored.vendored_partner:
        print(
            f"Found {len(scored.vendored_partner)} kube-score issue(s) in partner-maintained vendored "
            f"sub-chart(s) (missing resources.requests/.limits — wireable via this repo's "
            f"values.yaml per the same convention, but not yet triaged — reported, does not "
            f"fail the check):"
        )
        print_grouped_findings(
            scored.vendored_partner,
            key_fn=lambda f: (f[0], f[1], f[2]),
            item_fn=lambda f: f[3],
            label_fn=lambda k: f"[{k[0]}] {k[1]} ({k[2]}){_kube_score_line_suffix(k[1], scored.locations)}",
            items_label="issue(s)",
        )
        print()

    if scored.vendored_other:
        by_chart = Counter(chart for chart, _, _, _ in scored.vendored_other)
        print(
            f"{len(scored.vendored_other)} kube-score issue(s) across {len(by_chart)} other vendored "
            f"sub-chart(s) (missing resources.requests/.limits — still wireable via values.yaml, "
            f"but not yet triaged; not shown individually, does not fail the check)"
        )

    if not (scored.own_real or scored.vendored_partner or scored.vendored_other):
        print("OK: no kube-score container-resources findings in the rendered chart")


def check_kube_score(chart_dir: Path, extra_args: list[str]):
    """Check every rendered container declares CPU/memory requests and limits.

    Partner-vendor findings are listed per container, other-vendor ones only as a
    count. Vendored gaps are still ours to wire via values.yaml, but don't fail yet:
    the backlog is untriaged and some are upstream-blocked (no resources field
    exposed). Only own findings fail. Findings carry a "rendered line N" hint.
    """
    if shutil.which("kube-score") is None:
        return False, "kube-score is not installed (see --skip-kube-score to bypass)"

    check_id = quality_gates_kube_score_check_id(chart_dir)

    scored, error = _score_rendered_chart(chart_dir, extra_args, check_id)
    if scored is None:
        return False, error

    _print_kube_score_findings(scored)

    return scan_outcome(scored.own_real, scored.vendored_partner, scored.vendored_other)
