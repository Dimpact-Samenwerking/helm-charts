"""Version-transition cell/heading-suffix rendering ("X -> Y",
"(new)", "(unchanged)"), the version-pair/spec line replacers used
when bumping a pin in place, and describe_key_changes/missing_key_
change_lines_by_key's values.yaml-schema-diff prose."""

import re

from lib.upgradedoc_grouped_comments_and_changes_block import (
    VERSION_SPEC_RE,
    diff_keys,
    pair_renames,
)
from lib.upgradedoc_string_and_parsing_basics import normalize_version

VERSION_PAIR_RE = re.compile(r"(?P<source>[A-Za-z0-9][\w.\-]*)\s*(?P<arrow>→|->)\s*(?P<target>[A-Za-z0-9][\w.\-]*)")


FENCED_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)


HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def version_change_suffix(old, new, digest_only_change=False):
    """The bracketed status suffix alone for a version transition —
    "(new)" when there's no real baseline value at all (`old` falsy);
    "(digest changed)" when the version itself didn't change but its
    embedded digest did (`digest_only_change`); "(unchanged)" when the
    version is identical and nothing else did either; None when the
    version genuinely differs — nothing to render as a bare suffix, the
    caller renders the transition itself ("<old> <arrow> <new>", or
    "<old> -> <new>") instead.

    THE one place this exact four-way decision is made — real bug this
    closes: at least half a dozen call sites across this codebase used
    to hand-roll their own copy of it (some correctly, some not) —
    -upgrade.md's own table cell (canonical_version_cell/new_component_
    version_cell below), its own "### ..." Changes heading (lib.
    component_docs.make_changes_section's own app_heading/pin_suffix),
    a shared-image basename's own Changes heading (lib.image_docs.
    make_image_changes_section's own heading_suffix/per-path bullets),
    and the images-manifest's own per-entry comment/header-list item
    (image_manifest_version_text below, lib.image_docs.
    update_image_manifest's own item_text, lib.component_docs.
    update_images_manifest's own item_text, fix-doc-consistency's own
    add_missing_images_manifest_entries) — with two of those (update_
    image_manifest's own item_text; add_missing_images_manifest_
    entries' own version_text, which used a bare "no baseline_tag ->
    fall back to new_version itself" sentinel that made an "old ==
    new" DIGEST-only-change check wrongly fire for a genuinely brand-
    new image too, confirmed live: images-4.9.1.yaml's own zac otel
    sidecar comment read "0.158.0 -> 0.158.0" instead of "0.158.0
    (new)") actually getting it WRONG. Every caller now delegates here
    instead — see image_manifest_version_text (images-manifest's own
    ascii "->" arrow house style) and canonical_version_cell (-upgrade.
    md's own unicode "→" style) for the two current thin wrappers."""
    if not old:
        return "(new)"
    if normalize_version(old) == normalize_version(new):
        return "(digest changed)" if digest_only_change else "(unchanged)"
    return None


def image_manifest_version_text(old, new, digest_only_change=False):
    """The images-manifest's own house style for a version-change
    comment (an entry's own preceding comment, or a "# Changes:" header
    list item's own embedded version fragment) — ascii "->" arrow,
    matching this file type's own existing convention (as opposed to
    -upgrade.md's unicode "→" — see canonical_version_cell). See
    version_change_suffix for the shared new/unchanged/digest-changed
    decision both delegate to."""
    suffix = version_change_suffix(old, new, digest_only_change)
    return f"{new} {suffix}" if suffix else f"{old} -> {new}"


def canonical_version_cell(actual_source, actual_target):
    """A "Component versions" table cell in the established style:
    "<target> (unchanged)" when source==target, else "<source> → <target>"."""
    suffix = version_change_suffix(actual_source, actual_target)
    if suffix:
        return f"{actual_target} {suffix}"
    return f"{actual_source} → {actual_target}"


def new_component_version_cell(actual_target):
    """A "Component versions" table cell for a component with no baseline
    version at all — brand new this hop: "<target> (new)", the third
    member of canonical_version_cell's own "<target> (unchanged)" /
    "<source> → <target>" family."""
    return f"{actual_target} {version_change_suffix(None, actual_target)}"


def component_version_cell(old, new):
    """canonical_version_cell(old, new) when a baseline value exists;
    new_component_version_cell(new) when it doesn't AND `new` is a real
    version — never for the literal "-" not-applicable placeholder a
    sidecar row's own Helm-chart cell already legitimately uses (that's
    "no chart version of its own to compare", not "brand new"); bare
    `new` otherwise (e.g. `new` itself unresolvable). The single place
    both update_component_table (a fresh row) and fix-doc-consistency's
    own fix_component_version_table (correcting an existing one) decide
    this cell's text, so the two can't drift on when "(new)" applies.

    A native_components component's own Helm-chart cell (see lib.chart.
    native_components — a component with no chart at all to compare)
    reuses this exact "-" placeholder path too: callers pass old=None,
    new="-" for it, same as any chart-less sidecar row."""
    if old:
        return canonical_version_cell(old, new)
    if new and new != "-":
        return new_component_version_cell(new)
    return new


def replace_version_pair(line, new_source, new_target):
    """Replace the first "<source> -> <target>" (or "→") pair in line with
    new_source/new_target, preserving everything else (the "# <Name> — "
    prefix, arrow style, trailing newline)."""

    def repl(m):
        return f"{new_source} {m.group('arrow')} {new_target}"

    new_line, count = VERSION_PAIR_RE.subn(repl, line, count=1)
    return new_line if count else line


def replace_version_spec(line, new_spec):
    """Replace the first version-spec substring in `line` — either an
    "<source> -> <target>" (or "→") arrow pair (see replace_version_
    pair/VERSION_PAIR_RE), or a "<version> (new)"/"(unchanged)"/"(digest
    changed)" bracketed form (see image_manifest_version_text) — with
    the literal text `new_spec`, preserving everything else (name,
    prefix, em-dash, trailing newline) untouched. `line` unchanged
    (count 0) if it has neither shape at all — a genuinely free-form
    comment this was never meant to touch.

    The images-manifest's own per-entry comment analogue of replace_
    version_pair, generalized to ALSO replace a bracketed-suffix spec,
    not just an arrow pair — needed since the CORRECT text for an entry
    can switch from one shape to the other (e.g. a wrongly-written
    arrow "X -> X" must become the bracketed "X (new)" — real bug, real
    doc: images-4.9.1.yaml's own zac otel sidecar comment). Deliberately
    whole-string replacement (never capture-group reassembly like
    replace_version_pair's own `repl`) since the caller already has the
    FULL desired text from image_manifest_version_text, not just its
    two endpoints."""
    new_line, count = VERSION_SPEC_RE.subn(lambda m: new_spec, line, count=1)
    return new_line if count else line


def describe_key_changes(values_key, baseline_subtree, current_subtree):
    """One "- Key `<dotted>` was added/removed/renamed to `<dotted>`." line
    per top-level key change under this component — backtick-quoted,
    matching the convention verify-podiumd's own check looks for.

    Paths passed to diff_keys/pair_renames are relative to the subtree
    itself (path=()), NOT prefixed with values_key — pair_renames's own
    lookups walk baseline_subtree/current_subtree directly, so a
    values_key-prefixed path would never resolve (silently comparing None
    to None, which can pair completely unrelated keys as a false rename)."""
    diffs = list(diff_keys(baseline_subtree, current_subtree))
    added = [p for kind, p in diffs if kind == "added"]
    removed = [p for kind, p in diffs if kind == "removed"]
    renamed, added, removed = pair_renames(added, removed, baseline_subtree, current_subtree)

    def dotted(path):
        return ".".join((values_key,) + path)

    lines = []
    for path in added:
        lines.append(f"- Key `{dotted(path)}` was added.\n")
    for path in removed:
        lines.append(f"- Key `{dotted(path)}` was removed.\n")
    for old_path, new_path in renamed:
        lines.append(f"- Key `{dotted(old_path)}` was renamed to `{dotted(new_path)}`.\n")
    return lines


def missing_key_change_lines_by_key(text, changed_component_keys, baseline_values, values):
    """{values_key: [line, ...]} — every describe_key_changes() line for
    a changed component that isn't already mentioned (backtick-quoted,
    matching verify-podiumd's own check_values_deltas_content
    convention) anywhere in text, grouped by the component it's about —
    only keys with at least one missing line appear in the result. The
    per-key-preserving counterpart to a flattened "just append
    everything" list: each key's own missing lines need routing into
    THAT key's own values-deltas.md section (see lib.component_docs.
    sync_values_delta_sections), not appended as one shared flat block.
    A rename line carries two backtick spans (old and new key); both
    must already be mentioned for the line to count as covered, else
    it's reported as missing so a partial/stale rename mention still
    gets caught.

    "Mentioned" requires an EXACT match against an existing backtick
    span — never a substring check either direction. A real bug this
    guards against: ordinary prose using a short, generic word in
    backticks elsewhere in the doc (e.g. "environments override
    `registry`/`repository` ... but never `tag`", describing a general
    convention, not any one specific key) would otherwise silently mark
    EVERY dotted key path merely CONTAINING that word —
    `objecten.image.repository`, `keycloak-operator.operator.image.tag`,
    ... — as "already covered", dropping real, distinct
    additions/removals with no trace. A dotted path's own bare trailing
    segment already mentioned elsewhere without its full prefix (e.g.
    "ita.verlopenContactverzoekHerinneringNotificatie" referred to as
    just "verlopenContactverzoekHerinneringNotificatie" in prose) is
    deliberately reported as missing too — the exact same string shape
    as the bug above, with no mechanical way to tell the two apart, so
    there's no looser rule that catches one without the other. That
    trades an occasional harmless duplicate line (something already
    covered by differently-phrased prose gets suggested again) for
    actually catching every real omission, the much safer failure mode
    for a correctness check.

    A line whose exact text is already present verbatim in `text` is
    never reported either way, even if the "mentioned" check above
    somehow missed it — a second, independent backstop against
    re-adding content that's already there (see strip_fenced_code_blocks
    for the one known way the "mentioned" check itself can be fooled)."""
    backtick_spans = set(re.findall(r"`([^`]+)`", strip_fenced_code_blocks(text)))

    def mentioned(span):
        return span in backtick_spans

    by_key = {}
    for values_key in sorted(changed_component_keys):
        baseline_subtree = baseline_values.get(values_key, {}) if isinstance(baseline_values, dict) else {}
        current_subtree = values.get(values_key, {}) if isinstance(values, dict) else {}
        lines = []
        for line in describe_key_changes(values_key, baseline_subtree, current_subtree):
            spans_in_line = re.findall(r"`([^`]+)`", line)
            if line not in text and not all(mentioned(span) for span in spans_in_line):
                lines.append(line)
        if lines:
            by_key[values_key] = lines
    return by_key


def strip_fenced_code_blocks(text):
    """`text` with every ```...``` fenced code block blanked out. A single
    backtick or "**" sequence inside example code isn't a real inline-
    code/bold span, but naively pairing delimiters across the WHOLE
    document (see extract_mentioned_dependency_keys/
    missing_key_change_lines/lib.docs_consistency.
    check_values_deltas_content, all of which scan a free-form doc for
    such spans) desyncs every pairing after the first fence — silently
    hiding real, already-mentioned spans later in the doc from an
    "is this already covered" check, which then wrongly reports (or
    re-adds) content that's already there. Scan the stripped text for
    spans, never the original."""
    return FENCED_CODE_BLOCK_RE.sub("", text)


def strip_html_comments(text):
    """`text` with every <!-- ... --> HTML comment blanked out — same
    "scan the stripped text, never the original" precedent as strip_
    fenced_code_blocks above. Used by lib.component_docs.has_real_
    gemeente_specific_content: gemeente-specific.md's own STUB_TEMPLATES
    entry keeps its "## <gemeente> (<env>)" EXAMPLE heading inside one
    big HTML comment, so a real, human-added section of the same shape
    must never be confused with that commented-out template text."""
    return HTML_COMMENT_RE.sub("", text)


def append_to_doc(text, new_lines):
    """Append new_lines to the end of a doc, blank-line-separated from
    whatever's already there — the shared "just tack this on" convention
    used when a script adds content to an existing markdown doc."""
    if not new_lines:
        return text
    if text and not text.endswith("\n\n"):
        text = text.rstrip("\n") + "\n\n"
    return text + "".join(new_lines)
