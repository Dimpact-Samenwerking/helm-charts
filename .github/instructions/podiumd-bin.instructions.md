---
applyTo: "charts/podiumd/bin/**,charts/podiumd/etc/settings.yaml"
excludeAgent: "cloud-agent"
---

# Review: podiumd release tooling (`charts/podiumd/bin/`)

## One concept, one place

- Flag new code that computes something the code already computes. Search for
  callers of the same low-level helpers. These shared entry points must be
  reused, not rebuilt:

  | Concept | Use |
  | --- | --- |
  | image paths, repository groups, repo map, row names | `ChartImageIndex` / `chart_image_paths` |
  | current and baseline versions of a row or component | `resolve_component_row` |
  | which component a name or heading means | `resolve_component_identity` / `changes_heading_identities` |
  | the order of a generated list | `OrderingContext.key` / `path_order_key` |
  | generated vs user lines in a section | `owned_parts` with a `SectionShape` |
  | removed components and images | `removed_items` |
  | table row cells | `table_cells` / `set_row_cells` |

- Flag a near-copy of existing code, even one that differs in a detail, and a
  split or move that leaves a re-export facade.
- Name resolution is an exact or canonical match. Flag a new heuristic match
  (word span, substring, "closest", a synthesized display name).

## Writers and checker

- The checker reports exactly what the writers (`fix-doc-consistency`,
  `update-*`) would change, through the same functions. Flag a detection that
  exists only in the writer or only in the checker.
- New writer behaviour comes with a writer-then-checker test: run the writer,
  the checker reports nothing, a second writer run changes nothing.
- Writers change only generated lines. User text in `*-upgrade.md` and
  `*-values-deltas.md` is never changed or lost.

## Code quality

- Flag a disabled lint rule (`noqa`, `pyright: ignore`, `pylint: disable`)
  without a comment saying why on that line, and a vulture whitelist entry
  for code that could be removed.
- Unused code, tests, options and settings keys are removed in the same
  change.
- New tests are fully typed: annotated defs instead of lambdas, `assert x is
  not None` before using an Optional result.
- Comments say why, not what.
- A script's `--help` has a one-line summary, what it reads and writes, usage,
  arguments and examples. The same argument has the same name and wording in
  every script.
