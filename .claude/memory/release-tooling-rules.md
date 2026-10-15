# Release tooling: quality and process

Applies to `charts/podiumd/bin/` (scripts, `lib/`, tests) and
`charts/podiumd/etc/settings.yaml`. Reuse of existing code is in
[reuse-existing-logic.md](reuse-existing-logic.md); the commands are in
[`charts/podiumd/bin/README-coding.md`](../../charts/podiumd/bin/README-coding.md).

## Code quality

- No new static-analysis finding from any `run_python_checks` tool: ruff
  check (including its isort rules), ruff format, jscpd, pymarkdown, vulture,
  bandit, basedpyright strict (tests too) and pylint (including
  too-many-lines). Compare with the parent commit (a `git archive` copy),
  ignoring line numbers; "no errors in the new file" is not enough. When a
  module over too-many-lines grows, shrink or split it in the same change.
- Run `ruff format` only on the files you changed.
- Fix a finding instead of silencing it. Disable a rule only for a deliberate
  exception, on that one line, with a comment saying why.
- Remove what is unused in the same change: code, tests, values keys, script
  options, docs. Fix a vulture finding by removing the code, not by
  whitelisting it.
- Comments say why, not what; minimal and precise. This includes YAML
  comments in `etc/`.
- New tests are typed (basedpyright strict): annotated defs instead of
  lambdas, `assert x is not None` before using an Optional result.

## Scripts

- `--help` (module docstring or argparse text): a one-line summary, what the
  script reads and writes, Usage, arguments, examples; exit codes only when
  they matter. No rationale, history or `lib` internals.
- The same argument has the same name and the same explanation in every
  script (`<key>`, `<component>`, `<basename>`, `--dry-run`). Copy the
  wording from a script that already has it; also update the `README-*.md`
  and `.claude/commands` usage lines.
- A new script without argparse starts `main()` with
  `lib.cli.positional_args(__doc__, <count>)` or `lib.cli.exit_on_help(__doc__)`.
  Chart paths come from `lib.chart.paths`.
- A new `verify-podiumd` step goes at the end of its cost tier: file scans,
  then local parsing, then network calls, then Docker pulls and scans.

## Docs the scripts write

- `*-values-deltas.md` has one `## <component> <old> → <new> (chart …)`
  section per component, and no section for a pure version bump.
- `release-table.csv` is generated: regenerate it, never edit it by hand.

## Process

- Run `./run_python_checks` as its own command and read its exit code. Commit
  in a separate command, only after exit 0; never chain a commit after the
  checks with `;`.
- Ask the user before every commit and every push, on every branch.
- Never write "pre-existing failure" in a PR description without re-running
  that check first.
- Before `git reset --hard`, `git checkout -- <path>`, `git clean` or a
  branch switch: `git status --short`, and stash the whole tree when it is
  dirty. Undo a temporary overwrite from a scratch copy, not with
  `git checkout --`.
