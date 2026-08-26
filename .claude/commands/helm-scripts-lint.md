Lint the podiumd Python helper scripts (`charts/podiumd/bin/`) for unused imports and other pyflakes-class issues, using ruff.

Usage: `/helm-scripts-lint`

Why this skill exists: a `lib/` refactor of `verify-podiumd.py` once left ~65 dead imports behind (names re-exported "for compatibility" that the file itself never used). Config lives in `charts/podiumd/bin/ruff.toml` (`select = ["F"]` — pyflakes: F401 unused imports, F841 unused locals, etc.) so this class of drift gets caught going forward instead of relying on manual review.

The system Python here is externally-managed (PEP 668), so `pip install ruff` fails directly. Use a persistent local venv (not `/tmp` — that gets wiped) so the install only happens once:

```bash
VENV=~/.cache/podiumd-scripts-lint-venv
if [ ! -x "$VENV/bin/ruff" ]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q ruff
fi
"$VENV/bin/ruff" check charts/podiumd/bin/
```

Notes:
- `charts/podiumd/bin/ruff.toml` only exists on `feature/podiumd-scripts` — the scripts themselves follow the same branch-separation rule (never committed on release-content branches), so running this on a release branch will find no scripts (and no ruff.toml) to lint. That's expected, not a bug.
- `fix-oidc-config.py` (which stays in `charts/podiumd/scripts/`, not `bin/` — it's a one-off migration script, not part of this toolset) is excluded in `ruff.toml` — it predates and is unrelated to the verify-podiumd/lib toolset this rule was written for.
- Report findings; unused-import removals are safe to apply directly since they're dead code by definition, but retarget any test mock that referenced the removed import's name (see the cross-module monkeypatch note in `tests/verify-podiumd/conftest.py`) rather than just deleting and hoping nothing broke — always re-run the test suite after.
- Run this alongside the existing script test suite (`python3 -m pytest charts/podiumd/bin/tests/ -q`) before committing changes to `charts/podiumd/bin/`.
