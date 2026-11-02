"""Version-transition text ("X -> Y", "(new)", "(unchanged)") and in-place pin rewriters."""

import re

from typing import overload

from lib.upgradedoc.grouped_comments_and_changes_block import VERSION_SPEC_RE
from lib.upgradedoc.string_and_parsing_basics import normalize_version

VERSION_PAIR_RE = re.compile(r"(?P<source>[A-Za-z0-9][\w.\-]*)\s*(?P<arrow>→|->)\s*(?P<target>[A-Za-z0-9][\w.\-]*)")


HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def version_change_suffix(old: str | None, new: str | None, *, digest_only_change: bool = False):
    """The status suffix for a version transition, or None when the version really changed.

    "(new)" without `old`; "(digest changed)" or "(unchanged)" when the versions are equal.
    The single place this decision is made: every table cell, heading and images-manifest
    comment delegates here (hand-rolled copies got "X -> X" instead of "X (new)")."""
    if not old:
        return "(new)"
    if normalize_version(old) == normalize_version(new):
        return "(digest changed)" if digest_only_change else "(unchanged)"
    return None


def image_manifest_version_text(old: str | None, new: str | None, *, digest_only_change: bool = False):
    """Images-manifest version text: ascii "->" arrow, unlike -upgrade.md's "→"."""
    suffix = version_change_suffix(old, new, digest_only_change=digest_only_change)
    return f"{new} {suffix}" if suffix else f"{old} -> {new}"


def version_transition(old: str | None, new: str | None) -> str:
    """Upgrade-doc heading version text: "1.2 → 1.3", "1.3 (new)" or "1.3 (unchanged)"."""
    suffix = version_change_suffix(old, new)
    return f"{new} {suffix}" if suffix else f"{old} → {new}"


def chart_version_suffix(old_chart: str | None, new_chart: str | None) -> str:
    """Upgrade-doc heading chart clause: " (chart 1.2 → 1.3)", " (chart 1.3, unchanged)" or " (chart 1.3, new)".

    Empty for a native component (`new_chart == "-"`); "new" when there is no `old_chart`."""
    if new_chart == "-":
        return ""
    if old_chart is None:
        return f" (chart {new_chart}, new)"
    if normalize_version(old_chart) != normalize_version(new_chart):
        return f" (chart {old_chart} → {new_chart})"
    return f" (chart {new_chart}, unchanged)"


# pin_version_text's shapes: "`old` → `new`", or "`new` (<pin_status>)" (pin_kept).
PIN_TEXT_PATTERN = (
    r"`(?P<pin_old>[^`]+)` → `(?P<pin_new>[^`]+)`"
    r"|`(?P<pin_kept>[^`]+)` \((?P<pin_status>new|unchanged|digest changed)\)"
)


def pin_version_text(old: str | None, new: str | None) -> str:
    """Upgrade-doc pin bullet version text: "`1.2` → `1.3`", "`1.3` (new)" or "`1.3` (unchanged)"."""
    suffix = version_change_suffix(old, new)
    return f"`{new}` {suffix}" if suffix else f"`{old}` → `{new}`"


def canonical_version_cell(actual_source: str, actual_target: str | None):
    """A "Component versions" table cell in the established style:
    "<target> (unchanged)" when source==target, else "<source> → <target>"."""
    suffix = version_change_suffix(actual_source, actual_target)
    if suffix:
        return f"{actual_target} {suffix}"
    return f"{actual_source} → {actual_target}"


def new_component_version_cell(actual_target: str):
    """A "Component versions" cell for a component new this hop: "<target> (new)"."""
    return f"{actual_target} {version_change_suffix(None, actual_target)}"


@overload
def component_version_cell(old: str | None, new: str) -> str: ...


@overload
def component_version_cell(old: str | None, new: str | None) -> str | None: ...


def component_version_cell(old: str | None, new: str | None) -> str | None:
    """The "Component versions" cell text for old -> new; None when there is no `new`.

    canonical_version_cell with a baseline, else new_component_version_cell, except for the
    "-" not-applicable placeholder (chart-less sidecar or native component), returned as is.
    Shared by update_component_table and fix_component_version_table so "(new)" can't drift."""
    if new is None:
        return None
    if old:
        return canonical_version_cell(old, new)
    if new and new != "-":
        return new_component_version_cell(new)
    return new


def replace_version_spec(line: str, new_spec: str):
    """Replace the first version spec in `line` with `new_spec`; `line` unchanged if none.

    A spec is an arrow pair (VERSION_PAIR_RE) or a "<version> (new)"/"(unchanged)"/
    "(digest changed)" form. Whole-spec replacement, since the correct text can switch
    shape (a wrong "X -> X" must become "X (new)")."""
    new_line, count = VERSION_SPEC_RE.subn(lambda _m: new_spec, line, count=1)
    return new_line if count else line


def strip_html_comments(text: str):
    """`text` with every <!-- ... --> HTML comment blanked out.

    gemeente-specific.md's stub keeps an example "## <gemeente> (<env>)" heading in a comment."""
    return HTML_COMMENT_RE.sub("", text)
