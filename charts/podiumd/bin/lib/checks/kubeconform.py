"""Validate the `helm template` render against Kubernetes API schemas.

Catches unknown fields, wrong types and missing required fields that helm lint and
yamllint don't. Every run passes -cache, since one check makes several runs over
largely the same kinds.
"""

import json
import shutil

from collections import Counter
from pathlib import Path
from typing import NotRequired
from typing import TypedDict
from typing import TypeGuard

from lib.procutil import run
from lib.render_scope import ResourceLocations
from lib.render_scope import VendorBucketScan
from lib.render_scope import chart_name_from_source
from lib.render_scope import print_grouped_findings
from lib.render_scope import print_other_vendor_summary
from lib.render_scope import print_own_findings_heading
from lib.render_scope import print_partner_findings_heading
from lib.render_scope import resource_line
from lib.render_scope import scan_outcome
from lib.render_scope import scan_rendered_chart
from lib.settings import quality_gates_kubeconform_failing_statuses
from lib.yaml_types import is_yaml_mapping
from lib.yaml_types import shape_problem

KUBECONFORM_BASE_ARGS = [
    "-strict",  # also catch unknown/duplicate fields, not just type mismatches
    "-ignore-missing-schemas",  # CRDs (Keycloak, ECK, Redis, ...) have no registry schema
    "-verbose",
    "-summary",
    "-output",
    "json",
]


# One entry of kubeconform's JSON "resources" list (kind/name/version/
# status/msg), and a finding as (vendored chart or None for own, resource).
class KubeconformResource(TypedDict):
    """One entry of kubeconform's JSON "resources" list (only the fields read here)."""

    status: str
    kind: NotRequired[str]
    name: NotRequired[str]
    msg: NotRequired[str]


_RESOURCE_LIST_SHAPE = [{"status": str, "kind?": str, "name?": str, "msg?": str}]


def _is_resource_list(value: object) -> TypeGuard[list[KubeconformResource]]:
    return shape_problem(value, _RESOURCE_LIST_SHAPE) is None


def parse_kubeconform_output(stdout: str) -> list[KubeconformResource] | None:
    """The "resources" of kubeconform's JSON output, or None when it isn't
    JSON of that shape (a kubeconform bug/crash, not a chart problem)."""
    try:
        data: object = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    resources = data.get("resources") if is_yaml_mapping(data) else None
    return resources if _is_resource_list(resources) else None


KubeconformEntry = tuple[str | None, KubeconformResource]
VendoredKubeconformEntry = tuple[str, KubeconformResource]


def kubeconform_cache_dir():
    """kubeconform's -cache directory, shared across checkouts (schemas depend only on the
    Kubernetes version). Must exist beforehand: kubeconform won't create it."""
    return Path.home() / ".cache" / "podiumd-kubeconform-schemas"


def run_kubeconform(yaml_text: str) -> list[KubeconformResource] | None:
    """kubeconform's parsed "resources" for a YAML stream, or None if unparseable."""
    cache_dir = kubeconform_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    args = [*KUBECONFORM_BASE_ARGS, "-cache", str(cache_dir), "-"]
    result = run(["kubeconform", *args], input=yaml_text, capture_output=True, text=True)
    return parse_kubeconform_output(result.stdout)


def _kubeconform_group_key(entry: KubeconformEntry) -> tuple[str, str]:
    _chart, r = entry
    message = r.get("msg") or "(no message)"
    return r["status"], message.splitlines()[0]


def _kubeconform_group_label(key: tuple[str, ...]):
    status, first_line = key
    label = "ERROR" if status == "statusError" else "INVALID"
    return f"[{label:7s}] {first_line}"


def _kubeconform_item(entry: KubeconformEntry, locations: ResourceLocations):
    """ "<kind>/<name>" plus a "(rendered line N)" hint when the location is unambiguous.

    kubeconform reports no namespace, so a kind+name rendered more than once gets no hint.
    """
    _chart, r = entry
    kind, name = r.get("kind"), r.get("name")
    base = f"{kind}/{name}"
    line = resource_line(locations, kind, name)
    return f"{base} (rendered line {line})" if line else base


def _own_kubeconform_findings(
    own_docs: list[tuple[str, str]], failing_statuses: set[str]
) -> tuple[list[KubeconformResource] | None, str | None]:
    """(own findings, None), or (None, error) on unparseable output."""
    own_resources = run_kubeconform("".join(text for _source, text in own_docs))
    if own_resources is None:
        return None, "kubeconform produced unparseable output"
    return [r for r in own_resources if r.get("status") in failing_statuses], None


def _scan_vendored_charts(
    docs: list[tuple[str, str]], failing_statuses: set[str], vendor_map: dict[str, str]
) -> tuple[list[VendoredKubeconformEntry] | None, list[VendoredKubeconformEntry] | None, str | None]:
    """Validate each vendored sub-chart separately and split findings into (friendly, other).

    kubeconform's JSON has no source info, hence one run per sub-chart. Returns
    (None, None, error) on unparseable output.
    """
    vendored_by_chart: dict[str, list[str]] = {}
    for source, text in docs:
        vendored_by_chart.setdefault(chart_name_from_source(source), []).append(text)

    vendored_friendly: list[VendoredKubeconformEntry] = []
    vendored_other: list[VendoredKubeconformEntry] = []
    for chart, texts in vendored_by_chart.items():
        resources = run_kubeconform("".join(texts))
        if resources is None:
            return None, None, "kubeconform produced unparseable output"
        for r in resources:
            if r.get("status") not in failing_statuses:
                continue
            (vendored_friendly if chart in vendor_map else vendored_other).append((chart, r))
    return vendored_friendly, vendored_other, None


def _print_kubeconform_findings(scan: VendorBucketScan[KubeconformResource, VendoredKubeconformEntry]):
    """Print the own/vendored-friendly/vendored-other sections for `scan`."""
    if scan.own_real:
        print_own_findings_heading("kubeconform", len(scan.own_real))
        print_grouped_findings(
            [(None, r) for r in scan.own_real],
            key_fn=_kubeconform_group_key,
            item_fn=lambda entry: _kubeconform_item(entry, scan.locations),
            label_fn=_kubeconform_group_label,
            items_label="resource(s)",
        )
        print()

    if scan.vendored_friendly:
        print_partner_findings_heading("kubeconform", len(scan.vendored_friendly))
        print_grouped_findings(
            scan.vendored_friendly,
            key_fn=lambda entry: (entry[0], *_kubeconform_group_key(entry)),
            item_fn=lambda entry: _kubeconform_item(entry, scan.locations),
            label_fn=lambda k: f"{_kubeconform_group_label(k[1:])} — {k[0]} ({scan.vendor_map[k[0]]})",
            items_label="resource(s)",
        )
        print()

    if scan.vendored_other:
        by_chart = Counter(chart for chart, _ in scan.vendored_other)
        print_other_vendor_summary("kubeconform", len(scan.vendored_other), len(by_chart))

    if not (scan.own_real or scan.vendored_friendly or scan.vendored_other):
        print("OK: no kubeconform findings in the rendered chart")


def check_kubeconform(chart_dir: Path, extra_args: list[str]):
    """Validate the render against Kubernetes API schemas.

    Friendly-vendor findings are listed per resource, other vendored ones only as a
    count; vendored findings never fail. Only own findings (schema violations or
    unloadable resources) fail. CRDs without a known schema are skipped.
    """
    if shutil.which("kubeconform") is None:
        return False, "kubeconform is not installed (see --skip-kubeconform to bypass)"

    failing_statuses = quality_gates_kubeconform_failing_statuses(chart_dir)

    scan, error = scan_rendered_chart(
        chart_dir,
        extra_args,
        own_findings=lambda docs: _own_kubeconform_findings(docs, failing_statuses),
        vendored_findings=lambda docs, vendor_map: _scan_vendored_charts(docs, failing_statuses, vendor_map),
    )
    if scan is None:
        return False, error

    _print_kubeconform_findings(scan)

    return scan_outcome(scan.own_real, scan.vendored_friendly, scan.vendored_other)
