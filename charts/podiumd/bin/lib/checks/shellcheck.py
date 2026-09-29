"""Shellcheck every shell script embedded in a rendered container's command/args.

helm lint, kubeconform and yamllint treat these scripts as opaque strings.
"""

import json
import shutil

from collections import Counter
from pathlib import Path
from typing import NotRequired
from typing import TypedDict
from typing import TypeGuard

import yaml

from lib.chart.values_tree_primitives import text_at
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
from lib.settings import quality_gates_shellcheck_failing_levels
from lib.settings import quality_gates_shellcheck_shell_names
from lib.yaml_types import YamlValue
from lib.yaml_types import is_yaml_mapping
from lib.yaml_types import is_yaml_value
from lib.yaml_types import shape_problem


# One entry of shellcheck's JSON "comments" list (level/code/line/column/
# message), and a finding as (source, path, comment, kind, namespace, name).
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


ShellcheckFinding = tuple[str, str, ShellcheckComment, str | None, str | None, str | None]
# An embedded script as (source, path, shell, script_text, kind, namespace, name).
EmbeddedScript = tuple[str, str, str, str, str | None, str | None, str | None]


def _shell_name(token: YamlValue) -> str | None:
    return token.rsplit("/", 1)[-1] if isinstance(token, str) else None


def find_shell_scripts(
    obj: YamlValue, source: str, shell_names: set[str], path: str = ""
) -> list[tuple[str, str, str, str]]:
    """(source, path, shell, script_text) for every container invoking a shell with "-c".

    "-c" may be in command or args, in either order. Only `shell_names` binaries count.
    """
    found: list[tuple[str, str, str, str]] = []
    if isinstance(obj, dict):
        command = obj.get("command")
        args = obj.get("args")
        if isinstance(command, list) or isinstance(args, list):
            # Only list halves: a scalar command/args (bare-rendered value, CRD, hand-written Pod)
            # would raise `list + str`; yamllint/kubeconform report that instead.
            combined = (command if isinstance(command, list) else []) + (args if isinstance(args, list) else [])
            shell = _shell_name(combined[0]) if combined else None
            if shell in shell_names:
                for i, tok in enumerate(combined):
                    if tok == "-c" and i + 1 < len(combined) and isinstance(script := combined[i + 1], str):
                        found.append((source, path, shell, script))
                        break
        for key, value in obj.items():
            found.extend(find_shell_scripts(value, source, shell_names, f"{path}.{key}"))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            found.extend(find_shell_scripts(item, source, shell_names, f"{path}[{i}]"))
    return found


def extract_shell_scripts(docs: list[tuple[str, str]], shell_names: set[str]) -> list[EmbeddedScript]:
    """Every embedded shell script in (source, doc_text) `docs`, with the doc's (kind, namespace, name).

    The resource identity lets a finding be mapped to a rendered line via resource_line.
    """
    scripts: list[EmbeddedScript] = []
    for source, doc_text in docs:
        try:
            parsed = yaml.safe_load(doc_text)
        except yaml.YAMLError:  # noqa: S112 -- not a YAML resource, holds no shell script
            continue
        if parsed is None or not is_yaml_value(parsed):
            continue
        if isinstance(parsed, dict):
            kind = text_at(parsed, "kind")
            namespace = text_at(parsed, "metadata.namespace") or ""
            name = text_at(parsed, "metadata.name")
        else:
            kind = namespace = name = None  # not a single-object doc — no resource_line lookup possible
        for found_source, path, shell, script_text in find_shell_scripts(parsed, source, shell_names):
            scripts.append((found_source, path, shell, script_text, kind, namespace, name))
    return scripts


def run_shellcheck(shell: str, script_text: str) -> list[ShellcheckComment] | None:
    """shellcheck's "comments" for one script, or None if its output is unparseable."""
    result = run(["shellcheck", "-s", shell, "-f", "json1", "-"], input=script_text, capture_output=True, text=True)
    return parse_shellcheck_output(result.stdout)


def _shellcheck_group_key(finding: ShellcheckFinding):
    _source, _path, c, _kind, _namespace, _name = finding
    return c.get("level"), c.get("code"), c.get("message")


def _shellcheck_group_label(key: tuple[str, int, str]):
    level, code, message = key
    return f"[{level.upper():7s}] SC{code}: {message}"


def _shellcheck_location(finding: ShellcheckFinding, locations: ResourceLocations):
    """ "<source> (<path>) — script line <N>[:<col>] (rendered line M)" for one finding.

    Script line/column are within the embedded script; "rendered line M" is the
    containing resource's start line, omitted when unresolvable.
    """
    source, path, c, kind, namespace, name = finding
    line = c.get("line")
    if not line:
        base = f"{source} ({path})"
    else:
        column = c.get("column")
        pos = f"{line}:{column}" if column else str(line)
        base = f"{source} ({path}) — script line {pos}"
    if not kind or not name:
        return base
    rendered_line = resource_line(locations, kind, name, namespace=namespace)
    return f"{base} (rendered line {rendered_line})" if rendered_line else base


def _own_shellcheck_findings(
    own_docs: list[tuple[str, str]], shell_names: set[str], failing_levels: set[str]
) -> tuple[list[ShellcheckFinding] | None, str | None]:
    """Own scripts' failing_levels findings, or (None, error) on unparseable output."""
    own_real: list[ShellcheckFinding] = []
    for source, path, shell, script_text, kind, namespace, name in extract_shell_scripts(own_docs, shell_names):
        comments = run_shellcheck(shell, script_text)
        if comments is None:
            return None, "shellcheck produced unparseable output"
        own_real.extend((source, path, c, kind, namespace, name) for c in comments if c.get("level") in failing_levels)
    return own_real, None


def _vendored_script_result(entry: EmbeddedScript, failing_levels: set[str]):
    """(chart, findings, error) for one extract_shell_scripts entry; findings is None on error."""
    source, path, shell, script_text, kind, namespace, name = entry
    comments = run_shellcheck(shell, script_text)
    if comments is None:
        return None, None, "shellcheck produced unparseable output"
    findings: list[ShellcheckFinding] = [
        (source, path, c, kind, namespace, name) for c in comments if c.get("level") in failing_levels
    ]
    return chart_name_from_source(source), findings, None


def _vendored_shellcheck_findings(
    vendored_docs: list[tuple[str, str]], shell_names: set[str], failing_levels: set[str], vendor_map: dict[str, str]
) -> tuple[list[ShellcheckFinding] | None, list[ShellcheckFinding] | None, str | None]:
    """Vendored scripts' findings split into (friendly, other), or (None, None, error)."""
    vendored_friendly: list[ShellcheckFinding] = []
    vendored_other: list[ShellcheckFinding] = []
    for entry in extract_shell_scripts(vendored_docs, shell_names):
        chart, findings, error = _vendored_script_result(entry, failing_levels)
        if findings is None:
            return None, None, error
        (vendored_friendly if chart in vendor_map else vendored_other).extend(findings)
    return vendored_friendly, vendored_other, None


def _print_shellcheck_findings(scan: VendorBucketScan[ShellcheckFinding, ShellcheckFinding]):
    """Print the own/vendored-friendly/vendored-other sections for `scan`."""
    if scan.own_real:
        print_own_findings_heading("shellcheck", len(scan.own_real))
        print_grouped_findings(
            scan.own_real,
            key_fn=_shellcheck_group_key,
            item_fn=lambda f: _shellcheck_location(f, scan.locations),
            label_fn=_shellcheck_group_label,
            items_label="location(s)",
        )
        print()

    if scan.vendored_friendly:
        print_partner_findings_heading("shellcheck", len(scan.vendored_friendly))
        print_grouped_findings(
            scan.vendored_friendly,
            key_fn=_shellcheck_group_key,
            item_fn=lambda f: (
                f"{_shellcheck_location(f, scan.locations)} [{scan.vendor_map[chart_name_from_source(f[0])]}]"
            ),
            label_fn=_shellcheck_group_label,
            items_label="location(s)",
        )
        print()

    if scan.vendored_other:
        by_chart = Counter(chart_name_from_source(source) for source, *_rest in scan.vendored_other)
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

    shell_names = quality_gates_shellcheck_shell_names(chart_dir)
    failing_levels = quality_gates_shellcheck_failing_levels(chart_dir)

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
