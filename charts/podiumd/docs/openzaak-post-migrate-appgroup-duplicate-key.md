# OpenZaak startup failure: duplicate key on `admin_index_appgroup.slug`

## Symptom

After upgrading to PodiumD 4.6.2, `openzaak` pods fail to become ready. The pod starts but never passes its readiness probe. Checking the application logs reveals:

```
django.db.utils.IntegrityError: duplicate key value violates unique constraint "admin_index_appgroup_slug_key"
DETAIL:  Key (slug)=(accounts) already exists.
```

The error occurs during pod startup, inside a Django `post_migrate` signal handler.

## Root cause

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

## Affected versions

- PodiumD 4.6.2 (openzaak image as shipped)
- Only manifests on fresh pod starts (rolling restarts, upgrades) when `post_migrate` fires

## Workaround (applied during 4.6.2 rollout on aks-blue-ontw-dim1)

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

## Proper fix

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

## Related cascade failures

When openzaak pods are not ready, the following components also fail their health checks and become unavailable:

- `zac` — `OpenZaakReadinessHealthCheck DOWN` (ZAC polls openzaak on startup)
- Any component that validates its openzaak connection during readiness probing
