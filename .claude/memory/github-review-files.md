# GitHub review files follow the rules they copy

The Copilot reviewer reads only `.github/copilot-instructions.md` and
`.github/instructions/*.instructions.md`, and does not follow links. Those
files therefore hold copies of rules that live elsewhere. A change to a
source rule updates its copy in the same commit.

| When this changes | Update |
| --- | --- |
| `.github/copilot-instructions.md`: image references, resources, values defaults, Keycloak clients, seeding jobs, aks-blue rules | `.github/instructions/podiumd-chart.instructions.md` |
| `charts/podiumd/docs/_UPGRADE_DOCS_CHECKLIST.md`, the upgrade-doc or values-deltas rules in `release-tooling-rules.md`, or the images manifest format | `.github/instructions/podiumd-release-docs.instructions.md` |
| `reuse-existing-logic.md` (including its entry-point table) or `release-tooling-rules.md` | `.github/instructions/podiumd-bin.instructions.md` |
| `.github/copilot-instructions.md` § Markdown, or the `verify-podiumd` markdown settings | `.github/instructions/markdown.instructions.md` |
| `README.md` § Branching strategy, commit message conventions, local files that must not be committed, secrets rules | `.github/instructions/pr-review.instructions.md` |
| The checks named in `CLAUDE.md` § Pre-commit checklist, or a slash command used there is renamed or removed | `.github/pull_request_template.md` checklist |
| The sections of `.github/pull_request_template.md`, or the release PR layout | `.github/instructions/pr-review.instructions.md` and `CLAUDE.md` § PR descriptions |
| A chart directory under `charts/` or a top-level tooling directory is added, removed or renamed | `.github/CODEOWNERS` |
| A path, script, template or file named in an `*.instructions.md` file is renamed or removed | That instruction file's text and its `applyTo` globs |

## How to update

- Copy the rule as a short, direct bullet that says what to flag. Leave out
  rationale, history and commands: the reviewer only reads the diff.
- Keep each instruction file short: GitHub warns that the reviewer may
  overlook instructions in a long file. Split a file by path when it grows.
- Keep `excludeAgent: "cloud-agent"` so the files stay review-only.
- Name no path that `.gitignore` excludes, in rules or `applyTo` globs: it
  never appears in a PR diff. Check with `git check-ignore -v <path>`.
- Run `/markdown-lint` on the changed files; the files have YAML front
  matter, so pymarkdown needs `--enable-extensions front-matter`.
- CODEOWNERS owners per path are those who maintain the path; ask the user
  before adding or removing an owner.
