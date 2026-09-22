# Rules for `_UPGRADE_PATHS/`

These rules govern **every file in this folder**. They exist because these
documents are read by an operator at 09:00 with a deploy window open, not by
someone researching the release. Length is the enemy.

Written in English (new material everywhere in this repo is).

## The operator test — the governing rule

These files are **not a record of what changed** in a release. That record
already exists, in `charts/podiumd/Chart.yaml`, `charts/podiumd/values.yaml`
and `docs/images/images-<release>.yaml`, and it is authoritative in a way prose
never is.

These files carry only what someone **running the upgrade** must act on or be
warned about.

Before writing any paragraph, table row or section, answer:

> **What does the operator do differently because of this?**

If the answer is "nothing", it does not go in. No exceptions for material that
is interesting, hard-won, or expensive to have discovered.

## `<from>-to-<to>-values-deltas.md`

The list of edits to make to a values file. Nothing else — no prose, no
rationale, no "informational" section, no "no action needed" section.

Structure, exactly:

```markdown
# Values deltas — PodiumD <from> → <to>

## `podiumd.yml`

| Key | Action | From | To | When |
| --- | --- | --- | --- | --- |
| `kiss.settings.groepsmailboxVerplichting` | add | — | `false` | optional |
| `zaakbrug.image.tag` | change | `1.26.15` | `1.26.18` | only if pinned locally |

## `monitoring.yml`

| Key | Action | From | To | When |
| --- | --- | --- | --- | --- |
| `grafana.grafana.ini.auth.generic_oauth.scopes` | change | `openid email profile offline_access roles` | `openid email profile roles` | all |
```

One H2 per values file, one table per H2.

**`Action`** is one of: `add` · `change` · `remove` · `rename` ·
`set explicitly` (a chart default that flips, and should be pinned to keep the
old behaviour).

**`When`** is `all`, `optional`, `if pinned`, or a short condition
(`ftp mode`, `frankgateway.enabled`). Two or three words.

### Keep every cell under ~60 rendered characters

This is the rule the format lives or dies by, and it is the easy one to break.
A table is only worth using while it can be *scanned*; one long cell stretches
its column, collapses the other four to nothing, and forces horizontal
scrolling. At that point the table is worse than the prose it replaced.

Measure the **rendered** text — a link's URL does not count, its label does.

Nothing belongs in a cell except the key, the verb, the values and a two-word
condition. In particular, never put in a cell:

- a sentence, a clause with a comma, or anything with "because" / "unless"
- a 64-character digest, or any value longer than the column can hold
- a warning, however important
- an explanatory link with a sentence wrapped around it

### Where the caveat goes instead: `### Notes`

When a row genuinely needs a warning, a long value or a pointer, mark it in the
`When` cell with `[1]`, `[2]` … and write it under a `### Notes` heading below
the table. The table stays scannable; the caveat stays findable.

```markdown
| `pabc.seedJob.enabled` | add | — | `true` | optional [3] |

### Notes

**[3] Seeding replaces all PABC content.** Enable only on an environment whose
PABC database is empty. See [`enabling-pabc.md`](../apps/pabc/enabling-pabc.md).
```

A long value — a digest, a multi-key YAML shape — goes in a fenced block in its
Note, not in the `To` cell. The cell points at the Note.

One short line of plain text directly under a table is allowed when it applies
to the whole table (`Grafana login fails on every environment until this is
done.`). One line, not a paragraph.

The same cell-width rule governs the `Notes` column of the `## Component
versions` table in a `-upgrade.md`. `security · CRDs first · pinning changed`,
with the words linked — not a sentence about each.

### The exclusion test, per row

> **Would an operator have to type this into a values file?**

If no, the row does not belong. That excludes, always:

- chart-default image tags, digests and `sha` pins
- keys added under a subchart that no gemeente overrides
- anything you were about to label "informational" or "no action needed"
- `Key <x> was added` / `was removed` lines generated from a `values.yaml` diff

### When there is nothing to do

The entire body is one line:

```markdown
**No gemeente values changes are required for this hop.**
```

No placeholder paragraph, no explanation of why there is nothing.

## `<from>-to-<to>-upgrade.md`

What the operator must **do**: required manual steps, breaking changes, things
that break if ignored, and pointers to the companions.

- The `## Component versions` table is the **single source of truth for what
  moved**. No prose anywhere in the file restates an old → new version pair the
  table already carries.
- A component earns a `### ` section **only** when there is something to say
  that is not a version number — a manual step, a breaking change, a caveat, a
  migration, a consequence. A plain version bump with no operator consequence
  gets its table row and nothing else.
- Where a section is earned, the heading may carry the versions (that is
  navigation); the body must not. The body opens with the consequence.
- **No upstream changelogs, CVE write-ups or release-note transcription.** Link
  the upstream release page. A security release earns at most one word in the
  table's `Notes` column.
- Anything an operator types into a values file is a `-values-deltas.md` row,
  not a section here. Point at the deltas file; do not inline the keys.
- **A component deployed in no environment is out of scope entirely** — no
  section, no table row, no deltas row. When an environment starts running it,
  the hop that matters gets written up then.

`4.8.6-to-4.9.0-upgrade.md` is what an earned section looks like: its Keycloak
Operator section documents a rollback, what happens to the CRDs, and an explicit
"do not hand-carry these values into a 4.9.0 environment". None of that is in
any table.

## `<from>-to-<to>-gemeente-specific.md`

Findings that apply to **one gemeente or environment**, not to the release.
Empty until a rollout turns something up. Keep the commented-out entry
template at the bottom.

## `<from>-to-<to>-operators-crds.md`

Only when the hop adds or upgrades an operator or CRDs. Summary table
(component / change / CRD impact / action) plus the exact pre-deploy commands.
`helm upgrade` never applies CRD changes, so these run first.

## Where evicted prose goes

Usually nowhere — see the operator test. If it genuinely changes what an
operator does, it belongs in the `-upgrade.md` (a `kubectl` cleanup, a
prerequisite) or in `docs/apps/<app>/` (anything that outlives this one hop).
Deep background belongs in the JIRA issue or the PR, not here.
