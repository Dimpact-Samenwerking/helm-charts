"""State types shared by check_docs_consistency's phase helpers."""

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from lib.chart.chart_state import BaselineState
from lib.chart.chart_state import ComponentState
from lib.settings import DigestPinningException
from lib.upgradedoc.app_version_and_image_paths import ImagePath
from lib.upgradedoc.chart_image_index import ChartImageIndex
from lib.upgradedoc.removed_items import RemovedItem
from lib.upgradedoc.string_and_parsing_basics import TableRow

# A component as resolve_component_identity names it: ("dep", values_key)
# or ("sidecar", values-tree path).
ComponentIdentity = tuple[str, str | ImagePath]


@dataclass
class Findings:
    """check_docs_consistency's "checked" and "mismatched" accumulators."""

    checked: list[str]
    mismatches: list[str]


@dataclass
class DocQuery:
    """Which doc set to look for (podiumd_version, upgrade_docs_baseline, is_bare_version) and where."""

    doc_dir: Path
    podiumd_version: str
    upgrade_docs_baseline: str | None
    is_bare_version: bool


@dataclass
class StateImages:
    """The ChartImageIndex of the current and the baseline state; baseline is empty without a baseline_ref."""

    current: ChartImageIndex
    baseline: ChartImageIndex


@dataclass
class DocsCheckContext:
    """Read-only chart/baseline state for every phase helper, built by _build_docs_check_context.

    `current`/`baseline` are ComponentState (see lib.component_docs.changes_section).
    """

    chart_dir: Path
    current: ComponentState
    baseline: BaselineState
    baseline_ref: str | None
    doc_query: DocQuery
    images: StateImages
    actual_changed_keys: set[str]


@dataclass
class DocScanState:
    """The selected upgrade doc: its path, parsed rows, canonical sidecar/shared-image names and removed items."""

    doc_path: Path
    rows: list[TableRow]
    canonical_names: dict[str, ImagePath]
    removed: dict[str, RemovedItem] = field(default_factory=dict[str, RemovedItem])


@dataclass
class RowContext:
    """doc_path/baseline_ref for _check_component_rows' per-row sub-checks."""

    doc_path: Path
    baseline_ref: str | None


@dataclass
class RowLookup:
    """canonical_names/stale_names for _check_component_rows.

    `stale_names` rows were already reported by find_wrong_or_duplicate_dependency_claims,
    so they're skipped here rather than reported again.
    """

    canonical_names: dict[str, ImagePath]
    stale_names: set[str]


@dataclass
class ComponentRowsResult:
    """_check_component_rows' outputs, consumed by the later checks of the same section."""

    mismatches: list[str]
    # Identity -> resolved app version for "dep" rows; Changes headings must show it.
    resolved_app_by_identity: dict[ComponentIdentity, str]
    # Identity -> baseline app version (None when new); catches headings with the right
    # version but the wrong "(new)"/"(unchanged)"/"X -> Y" wording.
    baseline_app_by_identity: dict[ComponentIdentity, str | None]
    matched_sidecar_paths: set[ImagePath]


@dataclass
class ManifestEntryScan:
    """images_path/repo_map/sibling_fields for _check_images_manifest_entry."""

    images_path: Path
    repo_map: dict[str, ImagePath]
    sibling_fields: dict[ImagePath, DigestPinningException]
