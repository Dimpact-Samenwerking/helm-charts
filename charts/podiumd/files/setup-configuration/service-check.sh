# Compares the zgw_consumers services of $COMPONENT's values ($SERVICES: one
# "identifier api_root" pair per line) with its database. Exit 0: nothing in
# the way of setup-configuration. Exit 3: a Service holds an api_root under
# another slug; the log says what to change. Other exit codes: retried.
q() { psql -X -A -t -q -v ON_ERROR_STOP=1 "$@"; }

if ! TABLE=$(q -c "select to_regclass('public.zgw_consumers_service') is not null"); then
  echo "$COMPONENT: cannot reach its database ($PGHOST/$PGDATABASE)"
  exit 1
fi
if [ "$TABLE" != "t" ]; then
  echo "$COMPONENT: no zgw_consumers_service table yet (fresh install); nothing to check."
  exit 0
fi

FINDINGS=0
printf '%s\n' "$SERVICES" | while read -r ID ROOT; do
  [ -n "$ID" ] || continue
  HOLDER=$(echo "select slug from zgw_consumers_service where api_root = :'root';" | q -v root="$ROOT") || exit 1
  if [ -z "$HOLDER" ] || [ "$HOLDER" = "$ID" ]; then continue; fi
  TAKEN=$(echo "select slug from zgw_consumers_service where slug = :'slug';" | q -v slug="$ID") || exit 1
  if [ -z "$TAKEN" ] && [ "$AUTO_FIX" = "true" ]; then
    echo "update zgw_consumers_service set slug = :'slug' where slug = :'old';" | q -v slug="$ID" -v old="$HOLDER" || exit 1
    echo "$COMPONENT: renamed Service slug '$HOLDER' to '$ID' (api_root $ROOT)"
    continue
  fi
  if [ -z "$TAKEN" ]; then
    echo "$COMPONENT: Service '$HOLDER' already has api_root $ROOT, which the values give to '$ID'."
    echo "  Fix: rename that Service's slug to '$ID' in the admin (Configuratie > Services),"
    echo "  or set the values' identifier (and the *_service_identifier references) to '$HOLDER'."
  else
    echo "$COMPONENT: Service '$HOLDER' already has api_root $ROOT, and a Service '$ID' exists too."
    echo "  Fix: in the admin (Configuratie > Services), point the records that use '$HOLDER' at '$ID'"
    echo "  and delete '$HOLDER', or give '$ID' this api_root and delete '$HOLDER'."
  fi
  echo finding >> /tmp/findings
done || exit 1
if [ -f /tmp/findings ]; then FINDINGS=$(grep -c . /tmp/findings); fi
if [ "$FINDINGS" -gt 0 ]; then
  echo "$COMPONENT: $FINDINGS zgw_consumers service(s) would fail setup-configuration (zgw_consumers_service_api_root_key); fix them before the deploy."
  exit 3
fi
echo "$COMPONENT: zgw_consumers services match the database."
