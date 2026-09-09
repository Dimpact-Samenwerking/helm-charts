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
migration tool is available since 3.5.2.

**NOTE: this cannot be easily reverted for large forms, these should be copied first!**

```bash
# Dry run — lists forms with cyclic rules that cannot be auto-converted:
kubectl exec -n <ns> <openformulieren-pod> -- \
  python /app/src/manage.py enable_new_logic_evaluation_for_all_forms

# Apply (note: cannot be easily reverted for large forms; copy first):
kubectl exec -n <ns> <openformulieren-pod> -- \
  python /app/src/manage.py enable_new_logic_evaluation_for_all_forms --commit
```

#### 4. Catalogi API direct URL references (removed in 4.0) - migration script

ZGW APIs and Objects API registration backends that use direct
`informatieobjecttype` / case type URLs must be migrated to the
catalogue + type description format before 4.0. Open Forms 4.0 will refuse
to start if it detects legacy configuration.

A migration tool is available since 3.5.3:

```bash
# Dry run (reports issues without making changes):
kubectl exec -n <ns> <openformulieren-pod> -- \
  python /app/src/manage.py migrate_catalogi_api_urls

# Apply:
kubectl exec -n <ns> <openformulieren-pod> -- \
  python /app/src/manage.py migrate_catalogi_api_urls --no-dry-run
```

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
