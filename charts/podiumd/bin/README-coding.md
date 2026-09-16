# Coding Guide

Day-to-day commands for working on this `charts/podiumd/bin/` toolset — running
the test suite and the linters. For installing the tools themselves (`ruff`,
`pylint`, `pytest`, and the external CLIs `verify-podiumd` shells out to), see
[README-release-process.md's own Setup section](README-release-process.md#setup).

## Table of contents
- [Running the tests](#running-the-tests)
- [Running the linters](#running-the-linters)
  - [ruff (lint + format)](#ruff-lint--format)
  - [pylint (too-many-lines only)](#pylint-too-many-lines-only)
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

Both tools are configured from the single `pyproject.toml` in this same directory
(`[tool.ruff]`/`[tool.pylint]`) — no separate `ruff.toml`/`pylintrc` files, and
no flags needed for either to find it, as long as you're running them from
somewhere under `charts/podiumd/bin/`.

### ruff (lint + format)

```bash
cd charts/podiumd/bin

# Lint check only, no changes
ruff check .

# Lint check + apply every AUTO-fixable finding
ruff check --fix .
```

**Always review `ruff check --fix`'s own diff by hand before trusting it** —
it's usually safe, but it has produced real regressions in this codebase before:
a mechanical `if`/`elif` merge that collapsed a readable 3-branch condition into
one unreadable 187-character line, and (separately) a merge that mechanically
combined two `elif` branches that happened to test the exact same condition
(a genuine pre-existing dead-code bug) into a `X or X` expression — technically
correct, but worth cleaning up by hand rather than leaving it looking like that.

```bash
# Format check only, no changes (exits non-zero if anything would reformat)
ruff format --check .

# Actually reformat
ruff format .
```

`ruff format` is AST-preserving (re-serializes the same parse tree — unlike
`ruff check --fix`, it can't change behavior) and leaves docstring/comment
*prose* completely untouched, only restructuring code layout (line wrapping,
blank lines, quote style). Still worth running `ruff format --check` again
right after formatting once, to confirm it's idempotent (0 further changes) —
it always has been so far, but that's a cheap, worthwhile sanity check whenever
a lot of files change at once.

### pylint (too-many-lines only)

pylint is deliberately narrow here — see `pyproject.toml`'s own comment: it's
added on top of ruff for exactly one thing ruff has no rule for at all, total
module line count (`too-many-lines`, default threshold 1000 lines). It is not
a general second linter running in parallel with ruff.

```bash
cd charts/podiumd/bin
pylint lib/*.py $(find . -maxdepth 1 -type f -perm -u+x) $(find tests -name '*.py')
```

The explicit file list matters: pylint has no config option to auto-discover
this directory's own extensionless top-level scripts (`fix-doc-consistency`,
`verify-podiumd`, etc. — they have no `.py` suffix for it to glob on), so a
bare `pylint .` silently misses all of them. The command above explicitly
includes `lib/*.py`, every executable top-level script (via the same
`find -perm -u+x` pattern used elsewhere), and every test file under `tests/`
(several test modules are themselves well over 1000 lines).

## Before committing

No single command runs everything above in one shot (yet) — in order:

```bash
cd charts/podiumd/bin
python3 -m pytest -q
ruff check .
ruff format --check .
pylint lib/*.py $(find . -maxdepth 1 -type f -perm -u+x) $(find tests -name '*.py')
```

A failing `pytest` run or a `ruff check`/`pylint` finding introduced by your own
change should be fixed before committing; a pre-existing finding you didn't
touch is fine to leave (see this repo's own git history — findings get worked
through in batches, not all at once).
