"""Checks that every container in the rendered chart declares CPU/memory
requests AND limits — this repo's own documented convention
(.github/copilot-instructions.md's "Resource Requests and Limits"), not a
generic kube-score opinion (see quality_gates.kube_score_check_id in
lib.settings)."""

import json
import shutil

from collections import Counter
from dataclasses import dataclass

from lib.procutil import run
from lib.render_scope import OWN_TEMPLATES_PREFIX
from lib.render_scope import chart_name_from_source
from lib.render_scope import friendly_vendor_charts
from lib.render_scope import print_grouped_findings
from lib.render_scope import render_chart_docs
from lib.render_scope import resource_line
from lib.render_scope import scan_outcome
from lib.settings import quality_gates_kube_score_check_id


def run_kube_score(yaml_text):
    """Score a YAML stream with kube-score, returning the parsed list of
    scored objects (kube-score's own JSON schema — each a dict with
    object_name/checks/...) — or None if kube-score's own output couldn't
    be parsed as JSON (a kube-score bug/crash, not a chart problem).

    kube-score prints the JSON value "null" (not "[]") when a stream has
    no scoreable objects at all — e.g. a vendored sub-chart consisting
    entirely of CRDs, like eck-operator-crds. json.loads("null") returns
    None, which would otherwise be indistinguishable from "unparseable" —
    normalize it to [] so a CRD-only chart doesn't look like a crash."""
    result = run(["kube-score", "score", "-o", "json", "-"], input=yaml_text, capture_output=True, text=True)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return data or []


def extract_resource_findings(kube_score_objects, check_id):
    """From a kube-score run's scored objects, pull every non-skipped,
    below-full-grade `check_id` finding as (object_name, container,
    summary) — object_name is kube-score's own "Kind/apiVersion/
    namespace/name" identifier, container is the comment's "path" (the
    container the missing request/limit belongs to)."""
    findings = []
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


def parse_kube_score_object_name(object_name):
    """kube-score's own "Kind/apiVersion/namespace/name" identifier ->
    (kind, namespace, name), or (None, None, None) if it doesn't have that
    shape at all. apiVersion itself can contain a "/" (e.g. "batch/v1"),
    so kind is taken from the front and name/namespace from the back,
    with whatever's left in the middle (the actual apiVersion, unused
    here) joined back — a naive 4-way split would misparse a grouped
    apiVersion like "batch/v1" as two extra fields."""
    parts = object_name.split("/")
    if len(parts) < 4:
        return None, None, None
    return parts[0], parts[-2], parts[-1]


def _kube_score_line_suffix(object_name, locations):
    kind, namespace, name = parse_kube_score_object_name(object_name)
    if not kind:
        return ""
    line = resource_line(locations, kind, name, namespace=namespace)
    return f" — rendered line {line}" if line else ""


@dataclass
class KubeScoreResult:
    """Everything check_kube_score's own print/detail logic needs from a
    completed render+score pass: the rendered-line lookup (locations) and
    the three own/partner-vendor/other-vendor finding buckets. See
    _score_rendered_chart, which builds this."""

    locations: object
    own_real: list
    vendored_partner: list
    vendored_other: list


def _score_vendored_charts(docs, check_id, vendor_map):
    """Runs kube-score separately per vendored sub-chart (kube-score's own
    JSON carries no per-resource source info, so each sub-chart's docs are
    scored on their own — see check_kube_score's docstring), splitting
    findings into (vendored_partner, vendored_other) by vendor_map
    membership. Returns (None, None, error) if any sub-chart's kube-score
    output couldn't be parsed."""
    vendored_by_chart_docs = {}
    for source, text in docs:
        if not source.startswith(OWN_TEMPLATES_PREFIX):
            vendored_by_chart_docs.setdefault(chart_name_from_source(source), []).append(text)

    vendored_partner, vendored_other = [], []
    for chart, texts in vendored_by_chart_docs.items():
        objects = run_kube_score("".join(texts))
        if objects is None:
            return None, None, "kube-score produced unparseable output"
        bucket = vendored_partner if chart in vendor_map else vendored_other
        for object_name, container, summary in extract_resource_findings(objects, check_id):
            bucket.append((chart, object_name, container, summary))
    return vendored_partner, vendored_other, None


def _score_rendered_chart(chart_dir, extra_args, check_id):
    """Renders the chart, scores its own templates and every vendored
    sub-chart's templates (see _score_vendored_charts) with kube-score, and
    bundles the result into a KubeScoreResult. Returns (None, error) on any
    render/kube-score failure, else (KubeScoreResult, None)."""
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


def _print_kube_score_findings(scored):
    """Prints check_kube_score's three report sections (own/partner-vendor/
    other-vendor) for a completed KubeScoreResult -- see check_kube_score's
    own docstring for what each section means and why they're reported
    differently."""
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


def check_kube_score(chart_dir, extra_args):
    """Checks that every container in the rendered chart declares CPU/
    memory requests AND limits — this repo's own documented convention
    (.github/copilot-instructions.md's "Resource Requests and Limits"),
    not a generic kube-score opinion (see quality_gates.kube_score_check_id
    in lib.settings).

    Same own/partner-vendor/other-vendor scope split, and same per-item vs.
    aggregate-only reporting split, as check_yamllint/check_kubeconform/
    check_shellcheck: a partner-vendor finding is printed individually
    (grouped per container, by chart — kube-score's own JSON carries no
    per-resource source info, so — like check_kubeconform — each vendored
    sub-chart is scored as its own separate kube-score run), an
    other-vendor finding only ever gets a one-line aggregate count.

    The *fail* policy still differs from those three checks, though: a
    missing resource on ANY vendored sub-chart's container (partner or
    not) is still this repo's job to fix (wired via that sub-chart's
    values.yaml key, per the same documented convention) — it is not an
    upstream-code problem the way a YAML-style or shell-script issue is.
    So an other-vendor finding here is genuinely actionable, just
    deprioritized in the output (signal-to-noise: partner charts are the
    ones worth triaging first). Every per-item finding also gets a
    "— rendered line N" hint (see build_resource_locations/resource_line
    in lib.render_scope) — pipe the render to a file (render-podiumd)
    and jump straight there. It still does NOT fail the check yet,
    regardless of vendor: the current backlog is untriaged, and some gaps
    are upstream-blocked (the sub-chart's own template exposes no
    resources field at all for a given container — nothing to wire). Only
    an OWN finding fails; promoting vendored to failing is a deliberate
    future step once the backlog is resolved or written into
    docs/misc/resource-overview.md as an accepted/upstream-blocked gap."""
    if shutil.which("kube-score") is None:
        return False, "kube-score is not installed (see --skip-kube-score to bypass)"

    check_id = quality_gates_kube_score_check_id(chart_dir)

    scored, error = _score_rendered_chart(chart_dir, extra_args, check_id)
    if error:
        return False, error

    _print_kube_score_findings(scored)

    return scan_outcome(scored.own_real, scored.vendored_partner, scored.vendored_other)
