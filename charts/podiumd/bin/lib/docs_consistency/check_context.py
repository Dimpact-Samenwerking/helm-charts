"""Shared state types for lib.docs_consistency.check_docs_consistency:
the check context, the scan of the selected upgrade doc and the per-phase
result bundles threaded through its phase helpers."""

from dataclasses import dataclass
from pathlib import Path

from lib.component_docs.changes_section import BaselineState
from lib.component_docs.changes_section import ComponentState
from lib.settings import DigestPinningException
from lib.upgradedoc.app_version_and_image_paths import ImagePath
from lib.upgradedoc.string_and_parsing_basics import TableRow

# A component as resolve_component_identity names it: ("dep", values_key)
# or ("sidecar", values-tree path).
ComponentIdentity = tuple[str, str | ImagePath]


@dataclass
class Findings:
    """check_docs_consistency's own running "what got checked" / "what
    mismatched" accumulators, threaded through every phase helper in lib.docs_consistency
    instead of each one returning a pair the caller has to unpack and
    extend by hand -- that unpacking is exactly where this function's
    own local-variable count used to come from."""

    checked: list[str]
    mismatches: list[str]


@dataclass
class ImagePaths:
    """current/baseline image-tag-path maps, bundled since every check
    that compares "the image at this path" always needs both sides at
    once, never just one alone."""

    current: dict[ImagePath, str | None]
    baseline: dict[ImagePath, str | None]


@dataclass
class DocQuery:
    """The four values that together pick out WHICH doc set/filenames
    check_docs_consistency is even looking for (podiumd_version/
    upgrade_docs_baseline/is_bare_version) and where (doc_dir) --
    bundled purely to keep DocsCheckContext's own attribute count under
    pylint's too-many-instance-attributes, since these four always
    travel together anyway."""

    doc_dir: Path
    podiumd_version: str
    upgrade_docs_baseline: str | None
    is_bare_version: bool


@dataclass
class DocsCheckContext:
    """check_docs_consistency's own chart_dir/deps/values/baseline/
    image-path state, resolved once by _build_docs_check_context and
    read (never mutated) by every phase helper in lib.docs_consistency -- the "Component
    versions" table section, the images-manifest section and the
    values-deltas section all need some subset of exactly this, never
    anything else from the outer function. `current`/`baseline` are
    ComponentState (see lib.component_docs.changes_section) -- the same
    deps/values pairing resolve_component_row's own ResolutionContext
    already uses."""

    chart_dir: Path
    current: ComponentState
    baseline: BaselineState
    baseline_ref: str | None
    doc_query: DocQuery
    image_paths: ImagePaths
    actual_changed_keys: set[str]


@dataclass
class DocScanState:
    """Everything derived from the one selected upgrade doc itself (its
    path, parsed "Component versions" rows, and canonical sidecar/
    shared-image names) -- bundled since the missing-row, ordering and
    Changes-heading checks in lib.docs_consistency all need the same three, just to
    compare them against each other and against the doc's own text in
    different ways."""

    doc_path: Path
    rows: list[TableRow]
    canonical_names: dict[str, ImagePath]


@dataclass
class RowContext:
    """_check_component_rows' own doc_path/baseline_ref pair, threaded
    into each per-row sub-check purely to keep argument counts down."""

    doc_path: Path
    baseline_ref: str | None


@dataclass
class RowLookup:
    """_check_component_rows' own canonical_names/stale_names pair --
    bundled purely to keep that function's own argument count down.
    `stale_names` is duplicate_names | wrong_fuzzy_names (see
    find_wrong_or_duplicate_dependency_claims): rows already reported
    as wrong-or-stale there, skipped here so resolve_component_row
    doesn't ALSO report them as "does not match a dependency"."""

    canonical_names: dict[str, ImagePath]
    stale_names: set[str]


@dataclass
class ComponentRowsResult:
    """_check_component_rows' own five outputs, bundled since every one
    of them is consumed by a LATER check in the same "Component
    versions" table section (missing-row-for-changed-key, missing-
    sidecar-row, and Changes-heading checks) -- never by the row loop
    itself, so returning five separate values would just make every
    caller unpack all five immediately anyway."""

    mismatches: list[str]
    changed_component_keys: set[str]
    # (kind, values_key) identity -> its resolved, real app version (see
    # resolve_component_identity) — populated for every "dep" row whose
    # own actual_app_version resolves to something. Used by the Changes-
    # heading checks to catch a heading whose own text never shows an
    # app-version pair at all for a component that DOES have one.
    resolved_app_by_identity: dict[ComponentIdentity, str]
    # Same identity keying as resolved_app_by_identity, holding the
    # BASELINE side instead (None when the component is genuinely new at
    # the baseline). Used, together with resolved_app_by_identity, to
    # catch a Changes heading whose own "(new)"/"(unchanged)"/"X -> Y"
    # wording DISAGREES with what the row itself would render there — a
    # real, observed bug: a heading can show the CORRECT current version
    # yet the WRONG transition wording (e.g. "(unchanged)" for a
    # component that's actually new), which changes_heading_has_app_
    # version's own "is some version shown at all" check can never catch.
    baseline_app_by_identity: dict[ComponentIdentity, str | None]
    matched_sidecar_paths: set[ImagePath]


@dataclass
class ManifestEntryScan:
    """_check_images_manifest_entry's own images_path/repo_map/
    sibling_fields triple -- bundled purely to keep that function's own
    argument count down."""

    images_path: Path
    repo_map: dict[str, ImagePath]
    sibling_fields: dict[ImagePath, DigestPinningException]
