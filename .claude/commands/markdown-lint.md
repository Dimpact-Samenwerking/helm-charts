Lint Markdown with exactly the rules `verify-podiumd`'s "Markdown lint" step enforces, and fix every finding. This exists because that step **fails on any finding**: a doc that reads fine can still break the release verification (a fenced block without a language, a heading without blank lines around it, a trailing space). Getting it right when a file is written is much cheaper than a lint-fix PR later.

**Always run this after creating or editing any `*.md` file**, before committing.

Scope, the same as `verify-podiumd` (`find_markdown_files` in `lib/checks/markdown.py`): every `*.md` under `charts/podiumd/` must have **0 findings**, except:

- `charts/podiumd/README.md`, which helm-docs generates (use `/helm-docs-check`);
- `charts/podiumd/bin/` and vendored `charts/podiumd/charts/`;
- `docs/_UPGRADE_PATHS/` docs of past releases, which are frozen.

For other Markdown in the repo (`CLAUDE.md`, `.github/`, `.claude/commands/`, other charts): a new file must be clean, and an edited file must get no new findings. Command files in `.claude/commands/` start with plain text, not a heading, so MD041 does not apply to them.

Target files: `$ARGUMENTS` if given (one or more paths), otherwise every `*.md` changed on this branch:

```bash
git diff --name-only --diff-filter=AM "$(git merge-base HEAD origin/main)" -- '*.md'
git diff --name-only --diff-filter=AM -- '*.md'           # unstaged
git diff --name-only --diff-filter=AM --cached -- '*.md'  # staged
```

## 1. Get pymarkdown

Use the repo's own venv if it has one, otherwise a persistent local venv (not `/tmp`):

```bash
if [ -x .venv/bin/pymarkdown ]; then PYMD=.venv/bin/pymarkdown; else
  VENV=~/.cache/podiumd-markdown-venv
  [ -x "$VENV/bin/pymarkdown" ] || { python3 -m venv "$VENV" && "$VENV/bin/pip" install -q pymarkdownlnt; }
  PYMD="$VENV/bin/pymarkdown"
fi
```

The package is `pymarkdownlnt`; the command is `pymarkdown`.

## 2. Lint with the verify settings

```bash
"$PYMD" --return-code-scheme explicit \
  -d md013,md014 \
  -s 'plugins.md024.siblings_only=$!True' \
  scan <files>
```

These are the settings of `verify-podiumd`'s markdown check (`lib/checks/markdown.py`):

- `md013` (line length) and `md014` (commands-show-output) are disabled. If `charts/podiumd/etc/settings.yaml` exists and sets `quality_gates.markdown_disabled_rules`, use that list for `-d` instead.
- `md024` (duplicate headings) only applies to siblings under the same parent heading.
- Exit code `0` = clean, `4` = findings, anything else = pymarkdown itself failed.

## 3. Fix every finding

First let pymarkdown fix what it can safely fix (same flags, `fix` instead of `scan`), then lint again:

```bash
"$PYMD" -d md013,md014 -s 'plugins.md024.siblings_only=$!True' fix <files>
```

The rest needs a human decision. The ones that come up most in this repo:

| Rule | Fix |
| --- | --- |
| MD040 fenced-code-language | Give every fenced block a language: `yaml`, `bash`, `json`, `text`, ... |
| MD022 / MD031 / MD032 | Blank line before and after every heading, fenced block and list. |
| MD009 / MD012 | No trailing spaces; never two blank lines in a row. |
| MD033 no-inline-html | No `<br/>` or other HTML. End the sentence with a period, or start a new line or list item. |
| MD026 | No trailing punctuation (`:`, `.`) in a heading. |
| MD028 | Two adjacent blockquotes: join them with a `>` line, or put text between them. |
| MD024 | Two sibling headings with the same text: make them unique. |
| MD051 link-fragments | The `#anchor` must match a real heading: lowercase, spaces to `-`, punctuation and backticks dropped. |

Never "fix" a finding by disabling a rule or adding a pymarkdown ignore comment.

## 4. Upgrade docs: also check doc consistency

For `docs/_UPGRADE_PATHS/<baseline>-to-<target>-*.md` of the current release, `verify-podiumd` also runs its **doc consistency** step. Keep that doc's structure:

- Every level-3 section under the level-2 "Changes" heading must be a component version change with a row in the "Component versions" table, in the same order as `values.yaml`.
- Anything else (a behaviour change, a new check, a migration note) gets its own level-2 section after "Changes", not a level-3 section under it.

When the scripts (`charts/podiumd/bin/`, branch `feature/podiumd-scripts`) are available, run the real checks as the final gate:

```bash
python3 charts/podiumd/bin/verify-podiumd --include markdown,doc-consistency
```

## Report

```text
MARKDOWN LINT
  Files          : <n>
  Auto-fixed     : <n> finding(s) in <files>
  Fixed by hand  : <rule> x<n>, ...
  Result         : PASS (0 findings) | FAIL (<n> findings: <rule> <file>:<line>, ...)
```

Only report PASS with 0 findings; a finding left in is a FAIL.
