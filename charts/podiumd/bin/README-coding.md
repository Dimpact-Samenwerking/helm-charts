# Coding Guide

Commands for testing and linting the `charts/podiumd/bin/` toolset. For
installing the tools, see
[README-release-process.md's Setup section](README-release-process.md#setup).

## Table of contents

- [Running the tests](#running-the-tests)
- [Running the linters](#running-the-linters)
  - [ruff (lint + format)](#ruff-lint--format)
  - [shellcheck (shell scripts)](#shellcheck-shell-scripts)
  - [jscpd (duplicate code)](#jscpd-duplicate-code)
  - [vulture (dead code)](#vulture-dead-code)
  - [bandit (security)](#bandit-security)
  - [pylint](#pylint)
  - [basedpyright (type checking)](#basedpyright-type-checking)
- [Before committing](#before-committing)

## Running the tests

Run from `charts/podiumd/bin/`, not the repo root: there is no root-level
`conftest.py`/`pytest.ini`; each `tests/<script-name>/` is self-contained.

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

## Running the linters

All tools read `pyproject.toml` in this directory; run them from anywhere
under `charts/podiumd/bin/`.

The extensionless top-level scripts must be passed explicitly to every tool:
they only discover `*.py` files. Pass `lib` as a directory, not `lib/*.py`,
so subpackages are included.

### ruff (lint + format)

```bash
cd charts/podiumd/bin

# Lint check only, no changes
ruff check . $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x))

# Lint check + apply every AUTO-fixable finding
ruff check --fix . $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x))
```

Import order is part of `ruff check` (`I001`). `[tool.ruff.lint.isort]`
mirrors `[tool.isort]`, so `ruff check --select I --fix` and `isort` agree.
They attach comments between imports differently: fence such a block with
`# isort: off` / `# isort: on`.

Review the diff of `ruff check --fix` by hand: its mechanical merges can
produce unreadable conditions.

```bash
# Format check only, no changes (exits non-zero if anything would reformat)
ruff format --check . $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x))

# Actually reformat
ruff format . $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x))
```

### shellcheck (shell scripts)

```bash
shellcheck run_python_checks
```

Covers every file under `bin/` with a `sh`/`bash`/`dash`/`ksh` shebang, plus
any `*.sh` file. No configuration: a deliberate exception gets a
`# shellcheck disable=SCxxxx` comment on its line, with the reason.

### jscpd (duplicate code)

```bash
cd charts/podiumd/bin
jscpd --exit-code 1 --format python --mode weak --min-lines 4 --min-tokens 35 --reporters console \
    --ignore '**/__pycache__/**' \
    --ignore-pattern 'from .* import .*,import .*,SCRIPT_DIR = .*,sys\.path\.insert.*, +[a-z_]+: [^=\n]+\x2c\n' \
    lib $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x))
```

Fails on any copied block of 4+ lines, also with renamed identifiers: merge it
into one function. Not counted: import lines, the `sys.path` setup at the top
of every script, and typed parameter lines (two functions with the same
parameters are not a copy). A near-copy kept on purpose sits between
`# jscpd:ignore-start` and `# jscpd:ignore-end` with a comment saying why,
such as help texts that repeat another script's argument explanations;
`tests/lib/test_script_help_consistency.py` keeps those explanations equal.

jscpd finds copied code, not the same logic written differently; see the
"One concept, one place" rule in `.claude/memory/reuse-existing-logic.md`.

### vulture (dead code)

```bash
cd charts/podiumd/bin
vulture lib $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x))
```

`tests/` is excluded: pytest fixtures and mock parameters look like dead
code. The remaining false positives are in `ignore_names` in
`pyproject.toml`, each with its reason.

TypedDict fields read only by string key (`row["app"]`) look unused.
`run_python_checks` generates a whitelist for them, so the command above
reports those fields; use `./run_python_checks` for the real result.

A new finding is either dead code (delete it) or a false positive of those
kinds (add it to `ignore_names` with a reason).

### bandit (security)

```bash
cd charts/podiumd/bin
bandit -c pyproject.toml -r lib $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x)) -q
```

`tests/` is excluded: every `assert` would flag `B101`. `[tool.bandit]`
`skips` lists checks ruff's `S` rules already cover.

### pylint

pylint has no per-directory configuration, so it runs twice: `lib` and the
scripts get the full rule set; `tests/` also disables `TESTS_PYLINT_DISABLE`.

```bash
cd charts/podiumd/bin
pylint lib $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x))
PYTHONPATH=. pylint --disable="$TESTS_PYLINT_DISABLE" $(find tests -name '*.py')
```

Copy `TESTS_PYLINT_DISABLE` from `run_python_checks`. `PYTHONPATH=.` lets
pylint resolve `lib.*` imports in `tests/` without analyzing `lib`.

### basedpyright (type checking)

```bash
cd charts/podiumd/bin
basedpyright lib $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x)) tests
```

`typeCheckingMode = "strict"`: every parameter in `lib/` and the scripts
needs a type annotation. `tests/` allows unannotated fixture parameters and
monkeypatch lambdas (see `executionEnvironments` in `pyproject.toml`).

## Before committing

```bash
cd charts/podiumd/bin
./run_python_checks
```

Runs everything above, fastest first, stopping at the first failure. By
hand, in the same order (`pymarkdown` lints this directory's `*.md` with the
rules of `verify-podiumd`'s markdown check, which skips `bin/`):

```bash
cd charts/podiumd/bin
ruff check . $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x))
shellcheck run_python_checks
ruff format --check . $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x))
pymarkdown -d md013,md014 -s 'plugins.md024.siblings_only=$!True' scan ./*.md
vulture lib $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x))
bandit -c pyproject.toml -r lib $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x)) -q
pylint lib $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x))
PYTHONPATH=. pylint --disable="$TESTS_PYLINT_DISABLE" $(find tests -name '*.py')
basedpyright lib $(grep -l '^#!.*python' $(find . -maxdepth 1 -type f -perm -u+x)) tests
python3 -m pytest -q
```

Fix every test failure and new finding your change introduces;
pre-existing findings in code you did not touch may stay.
