# Coding Guide

Day-to-day commands for working on this `charts/podiumd/bin/` toolset — running
the test suite and the linters. For installing the tools themselves (`ruff`,
`pylint`, `pytest`, and the external CLIs `verify-podiumd` shells out to), see
[README-release-process.md's own Setup section](README-release-process.md#setup).

## Table of contents
- [Running the tests](#running-the-tests)
- [Running the linters](#running-the-linters)
  - [ruff (lint + format)](#ruff-lint--format)
  - [vulture (dead code)](#vulture-dead-code)
  - [bandit (security)](#bandit-security)
  - [pylint](#pylint)
  - [basedpyright (type checking)](#basedpyright-type-checking)
- [Before committing](#before-committing)

## Running the tests

All commands below are run from `charts/podiumd/bin/` itself (not the repo root —
the test suite has no root-level `conftest.py`/`pytest.ini`, each `tests/<script-name>/`
subdirectory is self-contained):

```bash
cd charts/podiumd/bin

# Everything
.venv/bin/python3 -m pytest -q  # or plain `python3 -m pytest -q` if pytest is on PATH

# One script's own tests only
python3 -m pytest -q tests/verify-release-table-with-podiumd/

# One test by name (substring match)
python3 -m pytest -q -k "keycloak"

# Verbose (see each test's own name, not just dots)
python3 -m pytest -q -v
```

The full suite currently runs ~2300+ tests in a couple of minutes.

## Running the linters

All four tools are configured from the single `pyproject.toml` in this same
directory (`[tool.ruff]`/`[tool.pylint]`/`[tool.bandit]`/`[tool.basedpyright]`)
— no separate `ruff.toml`/`pylintrc`/etc. files, and no flags needed for any
of them to find it, as long as you're running them from somewhere under
`charts/podiumd/bin/`.

### ruff (lint + format)

```bash
cd charts/podiumd/bin

# Lint check only, no changes
ruff check . $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x))

# Lint check + apply every AUTO-fixable finding
ruff check --fix . $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x))
```

The extensionless top-level scripts need to be passed explicitly — ruff only
auto-discovers `*.py` files via a bare `.`, the same file-discovery gap
`pylint`/`vulture` below have always had.

Import order is part of `ruff check` (rule `I001`). `[tool.ruff.lint.isort]` mirrors
`[tool.isort]`, so `ruff check --select I --fix` and `isort` give the same result — use
either. Both attach comment lines between imports differently, so fence such a block
with `# isort: off` / `# isort: on` (both tools honor it).

**Always review `ruff check --fix`'s own diff by hand before trusting it** —
it's usually safe, but it has produced real regressions in this codebase before:
a mechanical `if`/`elif` merge that collapsed a readable 3-branch condition into
one unreadable 187-character line, and (separately) a merge that mechanically
combined two `elif` branches that happened to test the exact same condition
(a genuine pre-existing dead-code bug) into a `X or X` expression — technically
correct, but worth cleaning up by hand rather than leaving it looking like that.

```bash
# Format check only, no changes (exits non-zero if anything would reformat)
ruff format --check . $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x))

# Actually reformat
ruff format . $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x))
```

`ruff format` is AST-preserving (re-serializes the same parse tree — unlike
`ruff check --fix`, it can't change behavior) and leaves docstring/comment
*prose* completely untouched, only restructuring code layout (line wrapping,
blank lines, quote style). Still worth running `ruff format --check` again
right after formatting once, to confirm it's idempotent (0 further changes) —
it always has been so far, but that's a cheap, worthwhile sanity check whenever
a lot of files change at once.

### vulture (dead code)

```bash
cd charts/podiumd/bin
vulture lib $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x))
```

Same file-discovery gap as pylint above (vulture only walks `*.py` files
under a directory, so the extensionless top-level scripts need to be passed
explicitly) — same fix, same command shape. `lib` is passed as a directory
(not a `lib/*.py` glob) so vulture recurses into subpackages like
`lib/component_docs/` too, same reason as pylint above — and, unlike a bare
`vulture .`, still leaves `tests/` out (see below).

**Deliberately excludes `tests/` entirely.** Vulture flags anything it can't
see a direct call to, and pytest fixtures / mock-function signature params
are structurally indistinguishable from real dead code under that test —
neither is ever "called" in vulture's own static sense. Trying it against
the whole tree once produced far more of that noise than real signal (see
git history). `pyproject.toml`'s own `[tool.vulture]` comment documents the
handful of individually-confirmed false positives this scoped invocation
still produces (`ignore_names`) and exactly why each one is safe to ignore.

A genuinely new finding here means: either it really is dead code (delete
it), or it's a new false positive of the same two shapes above — in which
case add it to `ignore_names` with the same kind of explanation, don't just
suppress it silently.

### bandit (security)

```bash
cd charts/podiumd/bin
bandit -c pyproject.toml -r lib $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x)) -q
```

Same file-discovery/`tests/`-exclusion shape as vulture above: `lib` is
passed as a directory so bandit recurses into subpackages, the extensionless
top-level scripts are passed explicitly, and `tests/` is deliberately left
out — every `assert` statement would otherwise flag `B101` (assert_used),
the same false-positive class ruff's own `tests/**` `S101` exemption
documents for the identical check under a different tool. `pyproject.toml`'s
own `[tool.bandit]` `skips` documents the checks ruff's `S` rules already
own elsewhere.

### pylint

Two invocations, because `pyproject.toml` has no per-directory scoping for
pylint's message-control (unlike ruff's `per-file-ignores`): `lib` and the
top-level scripts get the full default pylint rule set; `tests/`
additionally disables 7 checks that are false positives only there (pytest
fixture signatures, sys.path-hack conftest imports, shared assertion
boilerplate) — see `pyproject.toml`'s own `[tool.pylint."messages control"]`
comment for the full list and reasoning.

```bash
cd charts/podiumd/bin
pylint lib $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x))
PYTHONPATH=. pylint --disable="$TESTS_PYLINT_DISABLE" $(find tests -name '*.py')
```

`TESTS_PYLINT_DISABLE` is the rule list `run_python_checks` defines (and
explains): pylint false positives under `tests/`, plus the style and
structure rules not enforced for test code. Copy its value from there.

`lib` isn't an analyzed target in the second invocation, so its imports need
`PYTHONPATH=.` (not the target list) to resolve — otherwise pylint can't see
`lib.*` at all and every cross-package import in `tests/` raises a false
`import-error`.

The explicit file list matters: pylint has no config option to auto-discover
this directory's own extensionless top-level scripts (`fix-doc-consistency`,
`verify-podiumd`, etc. — they have no `.py` suffix for it to glob on), so a
bare `pylint .` silently misses all of them. `lib` is passed as a directory
argument, not a `lib/*.py` glob, so pylint recurses into subpackages like
`lib/component_docs/` too — same reason as vulture above.

### basedpyright (type checking)

```bash
cd charts/podiumd/bin
basedpyright lib $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x)) tests
```

`typeCheckingMode = "strict"` in `pyproject.toml` — every function parameter
in `lib/` and the scripts needs a type annotation. basedpyright walks
`tests/` too, with every rule except two: unannotated pytest fixture
parameters and monkeypatch lambdas are allowed there (see the
`executionEnvironments` entry in `pyproject.toml`). The extensionless
top-level scripts still need to be passed explicitly, same file-discovery
gap as pylint/vulture/bandit above.

**Baseline.** `.basedpyright/baseline.json` records the type errors that
existed when strict mode was adopted. basedpyright reads it automatically
and only reports errors that are not in it, so a new error still fails the
check. After fixing baselined errors, shrink the baseline:

```bash
basedpyright --writebaseline lib \
    $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x)) tests
```

Only rewrite the baseline to drop fixed errors, never to accept a new one:
check `git diff .basedpyright/baseline.json` removes entries only.

## Before committing

```bash
cd charts/podiumd/bin
./run_python_checks
```

Runs everything above fastest-first, stopping at the first failure: `ruff
check` (~0.03s) → `ruff format --check` (~0.05s) → `vulture` (~0.5s) →
`bandit` (~1.7s) → `pylint` (~6s) → `basedpyright` (~8.6s) → `pytest` (the
full suite, ~2-3 minutes) — measured, not guessed, so a real problem in the
cheap checks fails in well under a second instead of waiting on the full
test run first. Equivalent to running each command from the sections above
by hand, in this order:

```bash
cd charts/podiumd/bin
ruff check . $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x))
ruff format --check . $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x))
vulture lib $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x))
bandit -c pyproject.toml -r lib $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x)) -q
pylint lib $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x))
PYTHONPATH=. pylint --disable="$TESTS_PYLINT_DISABLE" $(find tests -name '*.py')
basedpyright lib $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x)) tests
python3 -m pytest -q
```

A failing `pytest` run or a `ruff check`/`pylint`/`bandit`/`basedpyright`
finding introduced by your own change should be fixed before committing; a
pre-existing finding you didn't touch is fine to leave (see this repo's own
git history — findings get worked through in batches, not all at once).
