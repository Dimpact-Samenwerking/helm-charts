Run the full pre-commit hygiene sweep for `charts/podiumd/values.yaml` and templates before staging a commit.

Sequence (stop on first failure, report which step failed):

1. **BOM check** — invoke `/helm-bomcheck`. Fail if a BOM was present (file just got rewritten; user must re-stage).
2. **Duplicate key scan** — invoke `/helm-dupecheck`. Fail if any non-list duplicate is reported.
3. **Lint with CI values** —
   ```bash
   helm lint charts/podiumd -f charts/podiumd/ci/lint-values.yaml
   ```
   Fail on errors. Warnings are reported but do not fail.
4. **Full render** — invoke `/helm-render-all`. Fail on render errors.

If `$ARGUMENTS` names one or more specific templates (e.g. `keycloak-cr.yaml`), also invoke `/helm-render <template>` for each as a final focused check (per the "always verify values.yaml with helm render" rule in memory).

Final report format:

```
PRECOMMIT SUMMARY
  BOM check      : PASS|FAIL (<detail>)
  Dupe check     : PASS|FAIL (<count>)
  Lint           : PASS|FAIL (<error count>, <warning count>)
  Full render    : PASS|FAIL
  Targeted render: <template> PASS|FAIL  (only if $ARGUMENTS given)
```

If everything passes, tell the user it is safe to `git add` and commit. Never commit automatically — wait for explicit approval.
