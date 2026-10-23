"""Read-only check before `manage.py migrate_catalogi_api_urls` (Open Forms 3.5.x).

migrate_catalogi_api_urls validates every registration backend and stops the
whole run on the first invalid one, printing only "The registration options
are not valid.". This script prints the reason per form, so they can be fixed
first. It changes nothing.

Run: kubectl exec -i deploy/openformulieren -c openformulieren -- \
       python src/manage.py shell < openforms-check-registration-options.py
"""

import json

from openforms.forms.models import FormRegistrationBackend
from openforms.forms.models import FormStep
from openforms.registrations.contrib.objects_api.config import ObjectsAPIOptionsSerializer
from openforms.registrations.contrib.zgw_apis.options import ZaakOptionsSerializer
from zgw_consumers.models import Service

SERIALIZERS = {"objects_api": ObjectsAPIOptionsSerializer, "zgw-create-zaak": ZaakOptionsSerializer}
V1_ONLY = "niet van toepassing in v2"
roots = [s.api_root for s in Service.objects.all()]


def urls(value):
    if isinstance(value, str):
        if value.startswith("http"):
            yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from urls(v)
    elif isinstance(value, list):
        for v in value:
            yield from urls(v)


problems = 0
for b in FormRegistrationBackend.objects.select_related("form").order_by("form_id"):
    form = f"form {b.form_id} {'(trash) ' if b.form._is_deleted else ''}{b.form.admin_name or b.form.name!r}"
    serializer = SERIALIZERS.get(b.backend)
    if serializer:
        s = serializer(data=b.options, context={"validate_business_logic": False})
        if not s.is_valid(raise_exception=False):
            problems += 1
            v1 = [k for k, v in s.errors.items() if all(V1_ONLY in str(m) for m in v)]
            rest = {k: v for k, v in s.errors.items() if k not in v1}
            if v1:
                print(f"V1_KEYS   {form} | {b.name}: remove {', '.join(sorted(v1))}")
            if rest:
                print(f"INVALID   {form} | {b.name}: {json.dumps(rest, default=str)[:300]}")
    for url in urls(b.options):
        if not any(url.startswith(r) for r in roots):
            problems += 1
            print(f"NO_SERVICE {form} | {b.name}: {url}")

# File components can name a document type by URL as well (registration.informatieobjecttype).
for step in FormStep.objects.select_related("form", "form_definition").order_by("form_id"):
    form = f"form {step.form_id} {'(trash) ' if step.form._is_deleted else ''}{step.form.admin_name or step.form.name!r}"
    for c in step.form_definition.iter_components():
        if c.get("type") != "file":
            continue
        url = (c.get("registration") or {}).get("informatieobjecttype") or ""
        if url.startswith("http") and not any(url.startswith(r) for r in roots):
            problems += 1
            print(f"NO_SERVICE {form} | step {step.form_definition.name!r} file {c.get('key')}: {url}")

print(f"SUMMARY {problems} problem(s); 0 means migrate_catalogi_api_urls should not stop on these")
