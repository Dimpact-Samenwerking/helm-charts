# Compares the zgw_consumers services of $COMPONENT's values ($SERVICES: one
# "identifier api_root" pair per line, in the order setup-configuration applies
# them) with its database, read with the app's own DB_* settings. Exit 0:
# nothing in the way of setup-configuration, or the database cannot be checked.
# Exit 3: a Service holds an api_root under another slug; the log says what to
# change. Other exit codes: retried.
q() { psql -X -A -t -q -v ON_ERROR_STOP=1 "$@"; }
# psql variables for \set: a quote inside single quotes is written twice.
lit() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/''/g")"; }

if [ -z "$DB_HOST" ]; then
  echo "$COMPONENT: no database settings from a previous release (first deploy of the app); nothing to check."
  exit 0
fi
export PGHOST="$DB_HOST" PGPORT="${DB_PORT:-5432}" PGDATABASE="$DB_NAME" PGUSER="$DB_USER" PGPASSWORD="$DB_PASSWORD"

# The check guards setup-configuration; it must not block an upgrade that would
# itself fix the connection (a new host or password in this release).
TABLE=""
for _ in 1 2 3; do
  TABLE=$(q -c "select to_regclass('public.zgw_consumers_service') is not null" 2>/tmp/psql.err) && break
  TABLE=""
  sleep 5
done
if [ -z "$TABLE" ]; then
  echo "$COMPONENT: WARNING: cannot read its database ($PGHOST/$PGDATABASE), so the zgw_consumers services were not checked:"
  sed 's/^/  /' /tmp/psql.err
  exit 0
fi
if [ "$TABLE" != "t" ]; then
  echo "$COMPONENT: no zgw_consumers_service table yet (before its first migration); nothing to check."
  exit 0
fi

IDS=$(printf '%s\n' "$SERVICES" | awk 'NF { print $1 }')
: > /tmp/findings
: > /tmp/renames
POS=0
printf '%s\n' "$SERVICES" | while read -r ID ROOT; do
  [ -n "$ID" ] || continue
  POS=$((POS + 1))
  # "1|<slug>" when a Service holds the api_root; its slug may be empty (Open Forms creates
  # its PDOK Locatieserver Service with get_or_create, without a slug).
  FOUND=$(echo "select count(*) || '|' || coalesce(max(slug), '') from zgw_consumers_service where api_root = :'root';" | q -v root="$ROOT") || exit 1
  HOLDER=${FOUND#*|}
  if [ "${FOUND%%|*}" = "0" ] || [ "$HOLDER" = "$ID" ]; then continue; fi
  # The holder is itself a service of the values: setup-configuration moves it to its
  # own api_root first when it comes earlier in the list, which frees this one.
  HOLDER_POS=$(printf '%s\n' "$IDS" | awk -v s="$HOLDER" '$1 == s { print NR; exit }')
  if [ -n "$HOLDER_POS" ] && [ "$HOLDER_POS" -lt "$POS" ]; then continue; fi
  if [ -n "$HOLDER_POS" ]; then
    echo "$COMPONENT: Service '$HOLDER' has api_root $ROOT, which the values give to '$ID'; the values move '$HOLDER' to another api_root, but only after '$ID' gets this api_root."
    echo "  Fix: list '$HOLDER' before '$ID' in zgw_consumers.services."
    echo finding >> /tmp/findings
    continue
  fi
  TAKEN=$(echo "select slug from zgw_consumers_service where slug = :'slug';" | q -v slug="$ID") || exit 1
  if [ -z "$TAKEN" ] && [ "$AUTO_FIX" = "true" ]; then
    printf '%s %s %s\n' "$ID" "$ROOT" "$HOLDER" >> /tmp/renames
    continue
  fi
  if [ -z "$TAKEN" ]; then
    echo "$COMPONENT: Service '$HOLDER' already has api_root $ROOT, which the values give to '$ID'."
    if [ -n "$HOLDER" ]; then
      echo "  Fix: rename that Service's slug to '$ID' in the admin (Configuratie > Services),"
      echo "  or set the values' identifier (and the *_service_identifier references) to '$HOLDER'."
    else
      echo "  Fix: give that Service the slug '$ID' in the admin (Configuratie > Services)."
    fi
  else
    echo "$COMPONENT: Service '$HOLDER' already has api_root $ROOT, and a Service '$ID' exists too."
    echo "  Fix: in the admin (Configuratie > Services), point the records that use '$HOLDER' at '$ID'"
    echo "  and delete '$HOLDER', or give '$ID' this api_root and delete '$HOLDER'."
  fi
  echo finding >> /tmp/findings
done || exit 1

FINDINGS=$(grep -c . /tmp/findings)
if [ "$FINDINGS" -gt 0 ]; then
  echo "$COMPONENT: $FINDINGS zgw_consumers service(s) would fail setup-configuration (zgw_consumers_service_api_root_key); fix them before the deploy. Nothing was changed."
  exit 3
fi
if [ -s /tmp/renames ]; then
  # All renames in one transaction, each only while the Service still holds the api_root
  # under the same slug; the unique slug stops a rename when the slug was taken meanwhile.
  {
    echo 'begin;'
    while read -r ID ROOT HOLDER; do
      echo "\\set slug $(lit "$ID")"
      echo "\\set root $(lit "$ROOT")"
      echo "\\set holder $(lit "$HOLDER")"
      echo "update zgw_consumers_service set slug = :'slug' where api_root = :'root' and coalesce(slug, '') = :'holder';"
    done < /tmp/renames
    echo 'commit;'
  } | q || exit 1
  while read -r ID ROOT HOLDER; do
    echo "$COMPONENT: renamed Service slug '$HOLDER' to '$ID' (api_root $ROOT)"
  done < /tmp/renames
fi
echo "$COMPONENT: zgw_consumers services match the database."
