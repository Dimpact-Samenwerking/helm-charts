# One concept, one place

Applies to all of `charts/podiumd/bin/`: scripts, `lib/` and tests. Code gets
better when it gets smaller while keeping the same or more functionality. A
change that adds lines for behaviour that already exists elsewhere is a
regression, even when the tests pass.

## Before writing new code

1. Name the concept, not the function: "the old app version of a component",
   "the doc row name of an image", "the order of doc items".
2. List the low-level helpers the new code would call
   (`historical_app_version_for_path`, `canonical_sidecar_row_names`,
   `paths_by_repository`, `match_dependency`, ...) and grep every caller of
   each. A caller that already computes the same thing is the place to
   extend; do not write a second one.
3. Use the shared entry point when one exists:

   | Concept | Use |
   | --- | --- |
   | image paths, repository groups, repo map, row names | `ChartImageIndex` / `chart_image_paths` |
   | a row's or component's current and baseline versions | `resolve_component_row` |
   | which component a name or heading means | `resolve_component_identity` / `changes_heading_identities` |
   | the order of any generated list | `OrderingContext.key` / `path_order_key` |
   | generated vs user lines in a section | `owned_parts` with a `SectionShape` |
   | removed components and images | `removed_items` |
   | which components already have a row | `rowed_component_keys` |
   | which manifest entries a `# Changes:` item covers | `covered_display_names` |
   | table row cells | `table_cells` / `set_row_cells` |

   Established fallback chains are reused, not rebuilt:
   - `image_paths_for` → `version_paths_for` for a dependency's own primary
     image (`actual_app_version`, `is_primary_rel_path`)
   - own values.yaml override → vendored subchart default →
     nested-subchart-documented default for a repository
     (`paths_by_repository`)
   - `repo_map` exact match → `resolve_entry_path` word match
     (`resolve_entry_image_path`)

## Writers and checker

- The checker reports exactly what the writers (`fix-doc-consistency`,
  `update-*`) would change, through the same functions: the writer's
  detection, or the writer run on the text in memory (as
  `removed_item_issues` does).
- A new repairable finding comes with its writer fix in the same change, and
  new writer behaviour comes with its check. Neither side gets its own copy
  of the detection.
- Fix a bug in the shared resolver, never in only the writer or only the
  checker. When the two disagree, the fix is making them share the code.
- Every new writer behaviour gets a writer-then-checker test: run the writer
  on a test chart, the checker reports nothing, and a second writer run
  changes nothing.

## While changing code

- Build shared inputs (path sets, name maps, values.yaml order, resolution
  contexts) through the shared builder, never inline in a caller.
- A near-copy of existing code is merged in the same change, including copies
  that differ only in a detail (how unmatched items sort, which fallback runs
  first).
- A split or move of code also merges the pieces that do the same thing;
  never leave a re-export facade.
- Deliberate duplication is allowed only for user-facing text that must be
  identical, such as the same argument's `--help` explanation. A test guards
  it (`tests/lib/test_script_help_consistency.py`), and jscpd skips it between
  `# jscpd:ignore-start` and `# jscpd:ignore-end`, with a comment saying why.

## Before committing

- `./run_python_checks` passes, including jscpd (copied code) and the help
  consistency test.
- Review the diff for "where else is this computed?": for each new function,
  search for the same concept by its low-level helpers (step 2 above),
  preferably with a review subagent that has not seen the change being
  written.
- The commit message names the existing functions that were checked, and
  which one was extended or why none fit.
