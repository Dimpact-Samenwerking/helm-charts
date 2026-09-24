"""Lints every shell script embedded in a container's command/args (this
chart's `command: [".../sh", "-c"], args: [<script>]` /
`command: [...], args: ["-c", <script>]` convention) — catches actual
shell bugs (bad quoting, undefined variables, portability issues) that
nothing else here checks; helm lint/kubeconform/yamllint all treat the
script as an opaque string."""

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
from lib.yaml_types import is_yaml_value
from lib.yaml_types import shape_problem


# One entry of shellcheck's JSON "comments" list (level/code/line/column/
# message), and a finding as (source, path, comment, kind, namespace, name).
class ShellcheckComment(TypedDict):
    """One entry of shellcheck's json1 "comments" list: the fields this
    module reads (positions are 1-based, within the script shellcheck was
    given)."""

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
    comments = data.get("comments") if isinstance(data, dict) else None
    return comments if _is_comment_list(comments) else None


ShellcheckFinding = tuple[str, str, ShellcheckComment, str | None, str | None, str | None]


def _shell_name(token: object):
    return token.rsplit("/", 1)[-1] if isinstance(token, str) else None


def find_shell_scripts(obj: YamlValue, source: str, shell_names: set[str], path: str = ""):
    """Recursively walk a parsed manifest (dict/list/scalar) looking for a
    container-shaped dict with a command/args pair that invokes a shell
    with "-c" (in either list, in either order — this chart uses both
    `command: [".../sh", "-c"], args: [<script>]` and
    `command: [...], args: ["-c", <script>]`). `shell_names` is the set of
    recognized shell binaries (see quality_gates.shellcheck_shell_names in
    lib.settings) — a container invoking anything else as its `command`
    is not treated as an embedded shell script at all. Returns (source,
    path, shell, script_text) tuples."""
    found = []
    if isinstance(obj, dict):
        command = obj.get("command")
        args = obj.get("args")
        if isinstance(command, list) or isinstance(args, list):
            # Take only the halves that are actually lists — a malformed
            # manifest where one of command/args is a scalar (a bare-rendered
            # `args: {{ .Values.x }}`, a CRD instance, a hand-written Pod)
            # would otherwise raise `list + str`; leave reporting that field
            # to yamllint/kubeconform rather than crashing the scan here.
            combined = (command if isinstance(command, list) else []) + (args if isinstance(args, list) else [])
            shell = _shell_name(combined[0]) if combined else None
            if shell in shell_names:
                for i, tok in enumerate(combined):
                    if tok == "-c" and i + 1 < len(combined) and isinstance(combined[i + 1], str):
                        found.append((source, path, shell, combined[i + 1]))
                        break
        for key, value in obj.items():
            found.extend(find_shell_scripts(value, source, shell_names, f"{path}.{key}"))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            found.extend(find_shell_scripts(item, source, shell_names, f"{path}[{i}]"))
    return found


def extract_shell_scripts(docs: list[tuple[str, str]], shell_names: set[str]):
    """docs: list of (source, doc_text) pairs, e.g. from
    split_rendered_by_source. Parses each doc_text as YAML and returns
    every embedded shell script found in it (see find_shell_scripts for
    `shell_names`), tagged with its source plus the containing resource's
    own (kind, namespace, name) — constant for every script found within
    the same doc, one resource per doc — so a finding can later be
    resolved back to a rendered-output line via lib.render_scope.
    resource_line."""
    scripts = []
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
    """Lint one embedded script, returning shellcheck's "comments" list (each
    a dict with level/code/line/message) — or None if shellcheck's own
    output couldn't be parsed as JSON (a shellcheck bug/crash, not a chart
    problem)."""
    result = run(["shellcheck", "-s", shell, "-f", "json1", "-"], input=script_text, capture_output=True, text=True)
    return parse_shellcheck_output(result.stdout)


def _shellcheck_group_key(finding: ShellcheckFinding):
    _source, _path, c, _kind, _namespace, _name = finding
    return c.get("level"), c.get("code"), c.get("message")


def _shellcheck_group_label(key: tuple):
    level, code, message = key
    return f"[{level.upper():7s}] SC{code}: {message}"


def _shellcheck_location(finding: ShellcheckFinding, locations: dict):
    """ "<source> (<path>) — script line <N>[:<col>] (rendered line M)" for
    one finding (source, path, comment, kind, namespace, name). The
    script line/column are shellcheck's own, against the embedded script
    text it was fed — position within that script, NOT a line number in
    the rendered YAML or the template file (shellcheck has no notion of
    either; `path` is what locates the right container's script among
    possibly several in the same manifest). "rendered line M" is this
    finding's containing resource's own start line in the full render
    (see build_resource_locations) — omitted if it can't be resolved
    (kind/name missing, or ambiguous — see resource_line)."""
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
    """Lints every embedded script found in this chart's own docs, keeping
    only failing_levels-severity comments. Returns (None, error) if any
    script's shellcheck output couldn't be parsed."""
    own_real: list[ShellcheckFinding] = []
    for source, path, shell, script_text, kind, namespace, name in extract_shell_scripts(own_docs, shell_names):
        comments = run_shellcheck(shell, script_text)
        if comments is None:
            return None, "shellcheck produced unparseable output"
        own_real.extend((source, path, c, kind, namespace, name) for c in comments if c.get("level") in failing_levels)
    return own_real, None


def _vendored_script_result(entry: tuple[str, ...], failing_levels: set[str]):
    """One extract_shell_scripts entry -> (chart, findings, error): lints
    the entry's script, keeping only failing_levels-severity comments as
    (source, path, comment, kind, namespace, name) findings. findings is
    None (and error set) if shellcheck's own output couldn't be parsed."""
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
    """Lints every embedded script found in vendored docs (see
    _vendored_script_result), splitting findings into (vendored_friendly,
    vendored_other) by vendor_map membership. Returns (None, None, error)
    if any script's shellcheck output couldn't be parsed."""
    vendored_friendly: list[ShellcheckFinding] = []
    vendored_other: list[ShellcheckFinding] = []
    for entry in extract_shell_scripts(vendored_docs, shell_names):
        chart, findings, error = _vendored_script_result(entry, failing_levels)
        if findings is None:
            return None, None, error
        (vendored_friendly if chart in vendor_map else vendored_other).extend(findings)
    return vendored_friendly, vendored_other, None


def _print_shellcheck_findings(scan: VendorBucketScan[ShellcheckFinding, ShellcheckFinding]):
    """Prints check_shellcheck's three report sections (own/vendored-
    friendly/vendored-other) for a completed VendorBucketScan -- see
    check_shellcheck's own docstring for what each section means and why
    they're reported differently."""
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


def check_shellcheck(chart_dir: Path, extra_args: list):
    """Lints every shell script embedded in a container's command/args
    (this chart's `command: [".../sh", "-c"], args: [<script>]` /
    `command: [...], args: ["-c", <script>]` convention) — catches actual
    shell bugs (bad quoting, undefined variables, portability issues) that
    nothing else here checks; helm lint/kubeconform/yamllint all treat the
    script as an opaque string.

    Same scope split as check_yamllint/check_kubeconform: this chart's OWN
    templates/ vs. a vendored sub-chart under charts/podiumd/charts/*. A
    dependency's script isn't ours to fix, so a vendored finding never
    fails — but a friendly-vendor/local dependency (see
    friendly_vendor_charts) is printed per-item; every other vendored
    sub-chart only ever gets a one-line aggregate count. Within OWN scope,
    error/warning-level findings (shellcheck's own "likely a real bug"
    tiers) fail the check; info/style (suggestions/preferences) aren't
    reported at all, same policy as check_yamllint's cosmetic findings.
    Every per-item location also gets a "(rendered line N)" hint — see
    _shellcheck_location/build_resource_locations — pointing at the
    containing resource's own start line in the full render (not the
    exact script line within it, which is a position kubeconform/
    kube-score/shellcheck's own line/column already covers separately)."""
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
