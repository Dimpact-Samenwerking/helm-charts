"""Update the docs for a single component's version bump: the upgrade
doc's "Component versions" table row + "## Changes" section, the
values-deltas doc, and docs/images/images-<target>.yaml. Shared by
update-component-version (a component's own app+chart bump — old_chart
may differ from new_chart) and update-image-version (a shared image
basename's bump, applied per component it happens to affect — old_chart
always equals new_chart there, since an image-only bump never touches
Chart.yaml).

See lib.component_docs.baseline_doc_stubs for the standard-doc-set
scaffolding (create_missing_docs, STANDARD_SUFFIXES, STUB_TEMPLATES),
lib.component_docs.images_manifest_changes_header for the images-
manifest "# Changes:" header/item bookkeeping, lib.component_docs.
changes_section for the table row/"## Changes" section itself,
lib.component_docs.values_delta_sections for the values-deltas doc's
own per-component sections, and lib.component_docs.images_manifest_
entries for updating/removing a component's own images-manifest
entries — all five split out of this module, kept as package siblings.
NO_CHANGES_CLAIMED_RE has no internal caller left in this package (only
update-component-version/update-image-version use it directly), so it
stays here as this module's own remaining content rather than moving
into one of those siblings.

Every path here (doc_dir/images_dir/values_path) is passed in explicitly
rather than read from a module-level constant, since the callers each
resolve their own CHART_DIR-relative paths independently."""

import re

NO_CHANGES_CLAIMED_RE = re.compile(r"no\s+gemeente\s+`?podiumd\.yml`?\s+changes\s+are\s+required", re.IGNORECASE)
