# Open Formulieren — Preparing for version 4.0

Open Formulieren 3.5.x is preparing for a major version. The below deprecations
were announced in the 3.5.x line and will become breaking changes in
Open Forms 4.0. No action is required for an upgrade of Open Formulieren to another
minor 3.x version. But form designers and admins should start the
migration work now.

Several scripts have been added to Open Formulieren that help in this migration.
This page lists those scripts.

## 1. Diagnostic script to check "disable next" logic actions
  
The "disable next" logic action now requires the target step to be explicitly specified.
When upgrading to a 3.5.x version, a migration runs automatically but cannot guarantee correctness in all cases. Open Formulieren offers a diagnostic script to identify forms where the automatic migration may have assigned the wrong step.
  
The below steps must be taken per gemeente.

   1. Run the diagnostic script:

   ```bash
   kubectl exec -n <ns> <openformulieren-pod> -- \
     python /app/bin/check_disable_next_logic_action.py
   ```

   Use `--show-all` for a complete list of all affected rules, not just the
   ambiguous ones.

   1. Share the result with form designers, they must review and correct any flagged rules manually.

### 2. Diagnostic script to check for cyclic or unstable logic

Open Forms 4.0 will enforce this as a hard requirement; start resolving now:

   ```bash
   kubectl exec -n <ns> <openformulieren-pod> -- \
     python /app/bin/report_invalid_form_logic.py
   ```

Report the output to form designers so they can work through the flagged forms before
the 4.0 upgrade.

This script has been available since version 3.5.0.

### 3. Migration script to remove  Legacy logic evaluation (removed in 4.0)

The old logic evaluation engine will be removed in Open Forms 4.0. A bulk
migration tool is available since 3.5.2. **Use it on 3.5.10 or later
(PodiumD 4.9.5):** up to 3.5.9 it can give logic rules the wrong order. Forms
converted with it on an older version get the correct order back when saved
once in the admin on 3.5.10.

**Up to 3.5.9 the command has no dry run:** run without arguments it converts
every form at once, and `--no-dry-run` fails as an unknown argument. The two
commands below only behave as described from 3.5.10 on.

**NOTE: this cannot be easily reverted for large forms, these should be copied first!**

```bash
# Dry run (Open Forms 3.5.10 and later only; on 3.5.9 and earlier this
# command converts every form) — lists forms with cyclic rules:
kubectl exec -n <ns> <openformulieren-pod> -- \
  python /app/src/manage.py enable_new_logic_evaluation_for_all_forms

# Apply (note: cannot be easily reverted for large forms; copy first):
kubectl exec -n <ns> <openformulieren-pod> -- \
  python /app/src/manage.py enable_new_logic_evaluation_for_all_forms --no-dry-run
```

#### 4. Catalogi API direct URL references (removed in 4.0) - migration script

ZGW APIs and Objects API registration backends that use direct
`informatieobjecttype` / case type URLs must be migrated to the
catalogue + type description format before 4.0. Open Forms 4.0 will refuse
to start if it detects legacy configuration.

A migration tool is available since 3.5.3. It stops the whole run, and
migrates nothing, on the first registration it can't validate. It then prints
only "The registration options are not valid." or "No service configured",
without the form. Two causes are common:

- Objects API registrations at options version 2 that still hold keys of
  version 1 (`content_json`, `productaanvraag_type`). Open Forms reports them
  as "niet van toepassing in v2" and doesn't use them. Saving the
  registration once in the form designer removes them.
- A registration, or a `file` component's `registration.informatieobjecttype`,
  that points at a Catalogi without a configured service, for example a URL of
  another environment. This is often on old copies of a form in the trash.

Check for both first, on Open Forms 3.5.10 (PodiumD 4.9.5), after the logic
conversion (section 3) and before the migration tool. The two scripts below
ship with PodiumD 4.10.0 (`charts/podiumd/scripts`); run them from a
helm-charts checkout of 4.10.0 against the environment that is still on 4.9.5.
They read from stdin, so `kubectl exec` needs `-i`. The check is read-only:
[`scripts/openforms-check-registration-options.py`](../../../scripts/openforms-check-registration-options.py).
It prints one line per problem: `V1_KEYS` (with the keys to remove),
`NO_SERVICE` (with the URL), or `INVALID` (any other error), and a summary
line. 0 problems means the migration tool won't stop on these:

```bash
kubectl exec -i -n <ns> deploy/openformulieren -c openformulieren -- \
  python /app/src/manage.py shell < charts/podiumd/scripts/openforms-check-registration-options.py
```

Remove the v1-only keys with
[`scripts/openforms-fix-registration-options.py`](../../../scripts/openforms-fix-registration-options.py).
It only touches registrations whose every error is a v1-only key, does all
changes in one transaction, and prints the original options as `BACKUP_JSON`:
save that output. Without `APPLY=1` it is a dry run that rolls back:

```bash
# Dry run:
kubectl exec -i -n <ns> deploy/openformulieren -c openformulieren -- \
  python /app/src/manage.py shell < charts/podiumd/scripts/openforms-fix-registration-options.py
# Apply, keeping the output (BACKUP_JSON):
kubectl exec -i -n <ns> deploy/openformulieren -c openformulieren -- \
  env APPLY=1 python /app/src/manage.py shell < charts/podiumd/scripts/openforms-fix-registration-options.py \
  | tee openforms-registration-options-<ns>.log
```

Fix `NO_SERVICE` references by hand (correct or clear the URL, or delete the
trashed form), and run the check again until it reports 0. Then run the
migration tool:

```bash
# Dry run (reports issues without making changes):
kubectl exec -n <ns> <openformulieren-pod> -- \
  python /app/src/manage.py migrate_catalogi_api_urls

# Apply:
kubectl exec -n <ns> <openformulieren-pod> -- \
  python /app/src/manage.py migrate_catalogi_api_urls --no-dry-run
```

If the dry run reports `Resolving the case/document types didn't converge to a
single catalogue`, the case type and document type sit in one catalogue, but
the ZGW API group's default catalogue (`catalogue_domain`/`catalogue_rsin`) is
another one. Set the catalogue of the case type on that form's registration
backend (in the form's registration settings), then run the dry run again.

Also check `file` component registration options for inconsistent catalogue
references (available since 3.5.5):

```bash
kubectl exec -n <ns> <openformulieren-pod> -- \
  python /app/bin/report_file_component_inconsistent_catalogues.py
```

### 5. "Clear on hide" behaviour change (4.0) - detection script

In 4.0, when a component is hidden and cleared, its variable will be removed
from the data entirely rather than reset to its default. Logic rules that
compare the variable to its default/empty value after it has been hidden may
stop triggering. A detection script is available since 3.5.3:

```bash
kubectl exec -n <ns> <openformulieren-pod> -- \
  python /app/bin/report_logic_with_deprecated_clear_on_hide_behavior.py
```

The output should be shared with form designers, so that they can review this, and
change their forms accordingly. To preserve current behaviour, add a
default value to the variable expression in the JSON logic trigger.
