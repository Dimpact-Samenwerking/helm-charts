# Reuse existing matching/resolution logic — don't reinvent it

Before adding a new matching/resolution/classification helper in `charts/podiumd/bin/lib/*.py`, search for existing functions handling the same concern and reuse or extend them — do not reimplement from first principles. This codebase has established fallback chains that must be reused, not duplicated, e.g.:

- `image_paths_for(component)` → `version_paths_for(component)` for a dependency's own primary image (see `actual_app_version`, `_is_dependency_primary_rel_path`)
- own values.yaml override → owning dependency's vendored subchart default → nested-subchart-documented default for repository resolution (see `lib.chart.paths_by_repository`)
- `repo_map` exact match → `resolve_entry_path`'s fuzzy word-matching fallback (see `resolve_entry_image_path`)

When two concerns need the same underlying test, factor it into one shared helper immediately rather than duplicating and reconciling later.
