# Open Zaak — known issues and configuration traps

## 1. Startup failure: duplicate key on `admin_index_appgroup.slug`

### Symptom

After upgrading to PodiumD 4.6.2, `openzaak` pods fail to become ready. The pod starts but never passes its readiness probe. Application logs show:

```
django.db.utils.IntegrityError: duplicate key value violates unique constraint "admin_index_appgroup_slug_key"
DETAIL:  Key (slug)=(accounts) already exists.
```

The error occurs during pod startup, inside a Django `post_migrate` signal handler.

### Root cause

`openzaak/utils/apps.py` connects the `update_admin_index` function to Django's `post_migrate` signal:

```python
# openzaak/utils/apps.py
post_migrate.connect(update_admin_index, sender=self)
```

The signal handler in `openzaak/utils/signals.py` attempts to reset the admin index fixture on every migration run:

```python
def update_admin_index(sender, **kwargs):
    AppGroup.objects.all().delete()
    ...
    call_command("loaddata", "default_admin_index", ...)
```

With **psycopg3**, `AppGroup.objects.all().delete()` and the subsequent `loaddata` are **not in the same transaction**. Under psycopg3's transaction semantics, the delete is issued in one implicit transaction that can be rolled back independently. If anything causes the outer transaction to be rolled back (or the delete is not committed before loaddata runs), the `accounts` slug already exists when `loaddata` tries to insert it, triggering the unique constraint violation.

This is a pre-existing image-level bug in openzaak that was exposed by the psycopg3 migration. The proper fix is to wrap the handler in `transaction.atomic()`.

### Affected versions

- PodiumD 4.6.2 (openzaak image as shipped)
- Only manifests on fresh pod starts (rolling restarts, upgrades) when `post_migrate` fires

### Workaround (applied during 4.6.2 rollout on aks-blue-ontw-dim1)

Delete the existing `AppGroup` rows via the Django management shell before the next pod restart, so the `loaddata` call finds an empty table and can insert cleanly:

```bash
kubectl exec -n podiumd --context <cluster> deploy/openzaak -- \
  //bin//bash -c "OTEL_SDK_DISABLED=True python src/manage.py shell -c \
  \"from django_admin_index.models import AppGroup; AppGroup.objects.all().delete(); print('deleted')\""
```

Then restart the deployment:

```bash
kubectl rollout restart -n podiumd --context <cluster> deploy/openzaak
```

> **Note on path doubling:** On Windows with Git Bash, paths like `/bin/bash` are mangled by MSYS. Use `//bin//bash` to prevent this when running `kubectl exec` from a Windows shell.

### Proper fix

Wrap `update_admin_index` in `transaction.atomic()` in the openzaak image:

```python
from django.db import transaction

def update_admin_index(sender, **kwargs):
    with transaction.atomic():
        AppGroup.objects.all().delete()
        ...
        call_command("loaddata", "default_admin_index", ...)
```

This ensures the delete and the fixture load are atomic and the unique constraint is never violated.

### Related cascade failures

When openzaak pods are not ready, the following components also fail their health checks and become unavailable:

- `zac` — `OpenZaakReadinessHealthCheck DOWN` (ZAC polls openzaak on startup)
- Any component that validates its openzaak connection during readiness probing

### See also

- [`openzaak-db-connection-pooling.md`](openzaak-db-connection-pooling.md) — separate proposal for uWSGI tuning + experimental psycopg3 connection pooling.

## 2. Migration failure: `permission denied` creating a trigger (1.29.3)

### Symptom

The `openzaak` pod fails to start after an upgrade to app version 1.29.3. The
migration step aborts and the pod restarts in a loop. The logs show a
`ProgrammingError` on the `documenten` migration:

```
django.db.utils.ProgrammingError: permission denied for table <table>
```

raised while `documenten.0037` runs `CREATE TRIGGER`. `<table>` is whichever
Open Zaak table the migration reached first.

### Root cause

Migration `documenten.0037` (new in 1.29.0) is the first Open Zaak migration
that creates a database **trigger**. Creating a trigger needs the `TRIGGER`
privilege on the target table.

Being the **owner** of the database — or even of the table — is not enough
when the privilege has been explicitly revoked: PostgreSQL records the
revocation in the table's ACL, and ownership does not override it. On
`ontw-dim1`, `TRIGGER` had been revoked on **106 of 129** tables as part of an
earlier hardening pass, so the migration could not run.

No earlier Open Zaak migration created a trigger, which is why this never
surfaced before 1.29.3.

### Affected versions

- Open Zaak 1.29.0 and later (PodiumD 4.9.0 and later)
- Only environments whose Open Zaak database has had `TRIGGER` revoked — a
  database created with default privileges is unaffected

### Prerequisite — grant `TRIGGER` *before* the Helm deploy

This must be fixed in the database **before** `helm upgrade` runs. The
migration runs automatically on pod startup, so there is no window in which to
repair it afterwards without a failed rollout and a restart.

Check first, against the Open Zaak database, substituting the database role
that Open Zaak connects as (`openzaak.settings.database.username` in the gemeente
`podiumd.yml`):

```sql
SELECT count(*) AS tables_without_trigger_privilege
FROM information_schema.tables t
WHERE t.table_schema = 'public'
  AND t.table_type = 'BASE TABLE'
  AND NOT has_table_privilege('<openzaak_db_user>',
                              format('%I.%I', t.table_schema, t.table_name),
                              'TRIGGER');
```

A non-zero count means the deploy will fail. Grant the privilege on the
existing tables, and set the default for tables created by future migrations:

```sql
GRANT TRIGGER ON ALL TABLES IN SCHEMA public TO "<openzaak_db_user>";

ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT TRIGGER ON TABLES TO "<openzaak_db_user>";
```

Re-run the check; it must return `0`. Then deploy.

`ALTER DEFAULT PRIVILEGES` applies only to tables created by the role that
issues it, so run it as the role that owns the schema (the same role the
migrations run as).

### Recovery if the deploy already failed

The failure is not destructive — the migration is transactional and rolls
back. Apply the grants above, then restart the deployment so the migration
runs again:

```bash
kubectl rollout restart -n podiumd --context <cluster> deploy/openzaak
```

### Applies to the other component databases too

Only the Open Zaak database was repaired on `ontw-dim1`. Any component
database that has had `TRIGGER` revoked will hit the same failure the first
time one of its migrations creates a trigger. If your environment applied a
privilege-hardening pass, run the check query above against every component
database before upgrading.

### See also

- [`../../_UPGRADE_PATHS/4.8.5-to-4.9.0-upgrade.md`](../../_UPGRADE_PATHS/4.8.5-to-4.9.0-upgrade.md) — the 4.9.0 upgrade guide, which carries this as a pre-deploy step.

