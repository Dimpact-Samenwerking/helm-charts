"""Remove v1-only keys from Objects API registrations at options version 2 (Open Forms 3.5.x).

`manage.py migrate_catalogi_api_urls` stops the whole run with "The
registration options are not valid." when an Objects API registration at
options version 2 still carries keys that only exist in version 1
(`content_json`, `productaanvraag_type`, ...). Open Forms reports those keys as
"niet van toepassing in v2" and does not use them. This script removes exactly
those keys, and only from registrations whose every error is of that kind;
anything else is listed under OTHER and left alone (see
openforms-check-registration-options.py for the reason per form).

Without APPLY=1 it is a dry run: it makes the same changes in one transaction
and rolls them back. With APPLY=1 it commits them. Either way it prints the
original options of every changed registration as BACKUP_JSON: save that
output before applying.

The match on "niet van toepassing in v2" assumes Open Forms' Dutch messages
(LANGUAGE_CODE nl, the PodiumD default).

Run on Open Forms 3.5.10, before migrate_catalogi_api_urls:
  kubectl exec -i -n <ns> deploy/openformulieren -c openformulieren -- \
    python /app/src/manage.py shell < charts/podiumd/scripts/openforms-fix-registration-options.py
  kubectl exec -i -n <ns> deploy/openformulieren -c openformulieren -- \
    env APPLY=1 python /app/src/manage.py shell < charts/podiumd/scripts/openforms-fix-registration-options.py
"""

import json
import os

from django.db import transaction
from openforms.forms.models import FormRegistrationBackend
from openforms.registrations.contrib.objects_api.config import ObjectsAPIOptionsSerializer

V1_ONLY = "niet van toepassing in v2"
APPLY = os.environ.get("APPLY") == "1"


def errors_of(options):
    serializer = ObjectsAPIOptionsSerializer(data=options, context={"validate_business_logic": False})
    return {} if serializer.is_valid(raise_exception=False) else serializer.errors


backup, fixed, other = {}, [], []
with transaction.atomic():
    for backend in FormRegistrationBackend.objects.filter(backend="objects_api").order_by("form_id"):
        errors = errors_of(backend.options)
        if not errors:
            continue
        v1_keys = {key for key, messages in errors.items() if all(V1_ONLY in str(m) for m in messages)}
        if set(errors) != v1_keys:
            other.append((backend.form_id, backend.name, json.dumps(errors, default=str)[:300]))
            continue
        backup[backend.pk] = dict(backend.options)
        for key in v1_keys:
            backend.options.pop(key, None)
        left = errors_of(backend.options)
        if left:
            msg = f"form {backend.form_id}: still invalid after removing {sorted(v1_keys)}: {left}"
            raise RuntimeError(msg)
        backend.save(update_fields=["options"])
        fixed.append((backend.form_id, backend.name, sorted(v1_keys)))
    if not APPLY:
        transaction.set_rollback(True)

print("BACKUP_JSON", json.dumps(backup, default=str))
for form_id, name, keys in fixed:
    print(f"{'FIXED' if APPLY else 'WOULD_FIX'} form {form_id} | {name}: removed {', '.join(keys)}")
for form_id, name, errors in other:
    print(f"OTHER     form {form_id} | {name}: {errors}")
print(f"SUMMARY {len(fixed)} registration(s) {'fixed' if APPLY else 'to fix (dry run, rolled back)'}, "
      f"{len(other)} with other errors")
