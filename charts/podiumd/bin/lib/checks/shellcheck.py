"""Shellcheck every shell script embedded in a rendered container's command/args.

helm lint, kubeconform and yamllint treat these scripts as opaque strings.
"""

import json
import shutil

from collections import Counter
from itertools import pairwise
from pathlib import Path
from typing import NamedTuple
from typing import NotRequired
from typing import TypedDict
from typing import TypeGuard

from lib.procutil import run
from lib.render_scope import RenderedDoc
from lib.render_scope import ResourceLocations
from lib.render_scope import VendorBucketScan
from lib.render_scope import chart_name_from_source
from lib.render_scope import parse_rendered_doc
from lib.render_scope import print_grouped_findings
from lib.render_scope import print_other_vendor_summary
from lib.render_scope import print_own_findings_heading
from lib.render_scope import print_partner_findings_heading
from lib.render_scope import resource_identity
from lib.render_scope import resource_line
from lib.render_scope import scan_outcome
from lib.render_scope import scan_rendered_chart
from lib.settings import gate_shellcheck_levels
from lib.settings import gate_shellcheck_shells
from lib.yaml_types import YamlMapping
from lib.yaml_types import YamlValue
from lib.yaml_types import is_yaml_mapping
from lib.yaml_types import shape_problem


class ShellcheckComment(TypedDict):
    """One entry of shellcheck's json1 "comments" list; positions are 1-based within the script."""

    level: str
    code: int
    message: str
    line: NotRequired[int]
    column: NotRequired[int]


_COMMENT_LIST_SHAPE = [{"level": str, "code": int, "message": str, "line?": int, "column?": int}]


def _is_comment_list(value: object) -> TypeGuard[list[ShellcheckComment]]:
    return shape_problem(value, _COMMENT_LIST_SHAPE) is None


def parse_shellcheck_output(stdout: str) -> list[ShellcheckComment] | None:
    """The "comments" of shellcheck's json1 output, or None when it isn't
    JSON of that shape (a shellcheck bug/crash, not a chart problem)."""
    try:
        data: object = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    comments = data.get("comments") if is_yaml_mapping(data) else None
    return comments if _is_comment_list(comments) else None


class ShellScript(NamedTuple):
    """A container's "<shell> -c <script>" found by find_shell_scripts, at values-tree-like `path` in `source`."""

    source: str
    path: str
    shell: str
    script_text: str


class EmbeddedScript(NamedTuple):
    """A shell script embedded in a rendered doc, with the doc's resource identity (None when not one object)."""

    source: str
    path: str
    shell: str
    script_text: str
    kind: str | None
    namespace: str | None
    name: str | None


class ShellcheckFinding(NamedTuple):
    """One shellcheck comment on an EmbeddedScript."""

    source: str
    path: str
    comment: ShellcheckComment
    kind: str | None
    namespace: str | None
    name: str | None


def _shell_name(token: YamlValue) -> str | None:
    return token.rsplit("/", 1)[-1] if isinstance(token, str) else None


def _list_items(value: YamlValue) -> list[YamlValue]:
    # Only list halves: a scalar command/args (bare-rendered value, CRD, hand-written Pod)
    # would raise `list + str`; yamllint/kubeconform report that instead.
    return value if isinstance(value, list) else []


def _inline_shell_script(container: YamlMapping, shell_names: set[str]) -> tuple[str, str] | None:
    """(shell, script) when `container`'s command + args run a `shell_names` shell with "-c <script>"."""
    combined = [*_list_items(container.get("command")), *_list_items(container.get("args"))]
    shell = _shell_name(combined[0]) if combined else None
    if shell is None or shell not in shell_names:
        return None
    for flag, script in pairwise(combined):
        if flag == "-c" and isinstance(script, str):
            return shell, script
    return None


def find_shell_scripts(obj: YamlValue, source: str, shell_names: set[str], path: str = "") -> list[ShellScript]:
    """A ShellScript for every container invoking a shell with "-c".

    "-c" may be in command or args, in either order. Only `shell_names` binaries count.
    """
    found: list[ShellScript] = []
    if isinstance(obj, dict):
        inline = _inline_shell_script(obj, shell_names)
        if inline is not None:
            found.append(ShellScript(source, path, *inline))
        for key, value in obj.items():
            found.extend(find_shell_scripts(value, source, shell_names, f"{path}.{key}"))
    elif isinstance(obj, list):
        for position, item in enumerate(obj):
            found.extend(find_shell_scripts(item, source, shell_names, f"{path}[{position}]"))
    return found


def extract_shell_scripts(docs: list[RenderedDoc], shell_names: set[str]) -> list[EmbeddedScript]:
    """Every embedded shell script in (source, doc_text) `docs`, with the doc's (kind, namespace, name).

    The resource identity lets a finding be mapped to a rendered line via resource_line.
    """
    scripts: list[EmbeddedScript] = []
    for source, doc_text in docs:
        parsed = parse_rendered_doc(doc_text)
        if parsed is None:
            continue
        kind, namespace, name = resource_identity(parsed)
        scripts.extend(
            EmbeddedScript(*script, kind, namespace, name) for script in find_shell_scripts(parsed, source, shell_names)
        )
    return scripts


def run_shellcheck(shell: str, script_text: str) -> list[ShellcheckComment] | None:
    """shellcheck's "comments" for one script, or None if its output is unparseable."""
    result = run(["shellcheck", "-s", shell, "-f", "json1", "-"], input=script_text, capture_output=True, text=True)
    return parse_shellcheck_output(result.stdout)


def _shellcheck_group_key(finding: ShellcheckFinding):
    comment = finding.comment
    return comment.get("level"), comment.get("code"), comment.get("message")


def _shellcheck_group_label(key: tuple[str, int, str]):
    level, code, message = key
    return f"[{level.upper():7s}] SC{code}: {message}"


def _shellcheck_location(finding: ShellcheckFinding, locations: ResourceLocations):
    """ "<source> (<path>) — script line <N>[:<col>] (rendered line M)" for one finding.

    Script line/column are within the embedded script; "rendered line M" is the
    containing resource's start line, omitted when unresolvable.
    """
    line = finding.comment.get("line")
    if line:
        column = finding.comment.get("column")
        pos = f"{line}:{column}" if column else str(line)
        base = f"{finding.source} ({finding.path}) — script line {pos}"
    else:
        base = f"{finding.source} ({finding.path})"
    if not finding.kind or not finding.name:
        return base
    rendered_line = resource_line(locations, finding.kind, finding.name, namespace=finding.namespace)
    return f"{base} (rendered line {rendered_line})" if rendered_line else base


def _script_findings(entry: EmbeddedScript, failing_levels: set[str]) -> list[ShellcheckFinding] | None:
    """`entry`'s failing_levels findings, or None when shellcheck's output is unparseable."""
    comments = run_shellcheck(entry.shell, entry.script_text)
    if comments is None:
        return None
    return [
        ShellcheckFinding(entry.source, entry.path, comment, entry.kind, entry.namespace, entry.name)
        for comment in comments
        if comment.get("level") in failing_levels
    ]


def _own_shellcheck_findings(
    own_docs: list[RenderedDoc], shell_names: set[str], failing_levels: set[str]
) -> tuple[list[ShellcheckFinding] | None, str | None]:
    """Own scripts' failing_levels findings, or (None, error) on unparseable output."""
    own_real: list[ShellcheckFinding] = []
    for entry in extract_shell_scripts(own_docs, shell_names):
        findings = _script_findings(entry, failing_levels)
        if findings is None:
            return None, "shellcheck produced unparseable output"
        own_real.extend(findings)
    return own_real, None


def _vendored_shellcheck_findings(
    vendored_docs: list[RenderedDoc],
    shell_names: set[str],
    failing_levels: set[str],
    vendor_map: dict[str, str],
) -> tuple[list[ShellcheckFinding] | None, list[ShellcheckFinding] | None, str | None]:
    """Vendored scripts' findings split into (friendly, other), or (None, None, error)."""
    vendored_friendly: list[ShellcheckFinding] = []
    vendored_other: list[ShellcheckFinding] = []
    for entry in extract_shell_scripts(vendored_docs, shell_names):
        findings = _script_findings(entry, failing_levels)
        if findings is None:
            return None, None, "shellcheck produced unparseable output"
        chart = chart_name_from_source(entry.source)
        (vendored_friendly if chart in vendor_map else vendored_other).extend(findings)
    return vendored_friendly, vendored_other, None


def _print_shellcheck_findings(scan: VendorBucketScan[ShellcheckFinding, ShellcheckFinding]):
    """Print the own/vendored-friendly/vendored-other sections for `scan`."""

    def vendored_item(finding: ShellcheckFinding) -> str:
        vendor = scan.vendor_map[chart_name_from_source(finding.source)]
        return f"{_shellcheck_location(finding, scan.locations)} [{vendor}]"

    if scan.own_real:
        print_own_findings_heading("shellcheck", len(scan.own_real))
        print_grouped_findings(
            scan.own_real,
            key_fn=_shellcheck_group_key,
            item_fn=lambda finding: _shellcheck_location(finding, scan.locations),
            label_fn=_shellcheck_group_label,
            items_label="location(s)",
        )
        print()

    if scan.vendored_friendly:
        print_partner_findings_heading("shellcheck", len(scan.vendored_friendly))
        print_grouped_findings(
            scan.vendored_friendly,
            key_fn=_shellcheck_group_key,
            item_fn=vendored_item,
            label_fn=_shellcheck_group_label,
            items_label="location(s)",
        )
        print()

    if scan.vendored_other:
        by_chart = Counter(chart_name_from_source(finding.source) for finding in scan.vendored_other)
        print_other_vendor_summary("shellcheck", len(scan.vendored_other), len(by_chart))

    if not (scan.own_real or scan.vendored_friendly or scan.vendored_other):
        print("OK: no shellcheck findings in the rendered chart")


def check_shellcheck(chart_dir: Path, extra_args: list[str]):
    """Shellcheck every embedded container shell script in the render.

    Own error/warning findings fail; info/style aren't reported. Vendored findings never
    fail: friendly-vendor ones are listed, other vendored charts get one count line.
    Locations carry the containing resource's "(rendered line N)".
    """
    if shutil.which("shellcheck") is None:
        return False, "shellcheck is not installed (see --skip-shellcheck to bypass)"

    shell_names = gate_shellcheck_shells(chart_dir)
    failing_levels = gate_shellcheck_levels(chart_dir)

    scan, error = scan_rendered_chart(
        chart_dir,
        extra_args,
        own_findings=lambda docs: _own_shellcheck_findings(docs, shell_names, failing_levels),
        vendored_findings=lambda docs, vendor_map: _vendored_shellcheck_findings(
            docs, shell_names, failing_levels, vendor_map
        ),
    )
    if scan is None:
        return False, error

    _print_shellcheck_findings(scan)

    return scan_outcome(scan.own_real, scan.vendored_friendly, scan.vendored_other)
