"""Update the docs for one component's version bump.

Covers the upgrade doc's "Component versions" row and "## Changes" section,
the values-deltas doc, and docs/images/images-<target>.yaml. Used by
update-component-version and update-image-version (where old_chart always
equals new_chart). Paths are passed in explicitly by each caller."""

import re

NO_CHANGES_CLAIMED_RE = re.compile(r"no\s+gemeente\s+`?podiumd\.yml`?\s+changes\s+are\s+required", re.IGNORECASE)
