#!/usr/bin/env bash
#
# scan.sh - one-off Dutch-PII sweep of Loki. For each category it pushes a
# server-side LogQL regex filter (only candidate lines transfer), then
# validates + MASKS locally via classify.awk. Output is a masked report on
# /report; raw PII is never written or printed.
#
# Pagination matches the export tool: forward by query_range, ns cursors
# compared/sorted as strings (ns ~1.78e18 overflows jq's 2^53 double).
#
set -euo pipefail

GATEWAY="${GATEWAY:?GATEWAY not set}"
QUERY="${QUERY:?QUERY not set}"          # base stream selector, e.g. {namespace=~".+"}
START_NS="${START_NS:?START_NS not set}"
END_NS="${END_NS:?END_NS not set}"
LIMIT="${LIMIT:-5000}"

OUTDIR="/report"
FINDINGS="${OUTDIR}/findings.tsv"        # masked: cat \t ns \t app \t pod \t masked
REPORT="${OUTDIR}/pii-report.txt"
ENDPOINT="${GATEWAY}/loki/api/v1/query_range"
BT='`'                                   # LogQL raw-string delimiter (no backslash doubling)

mkdir -p "${OUTDIR}"
: > "${FINDINGS}"

# Category name  ->  RE2 line-filter pushed to Loki (validated again in awk).
CATS="bsn email iban phone postcode creditcard fieldkey"
filter_for() {
  case "$1" in
    bsn)        echo '[0-9]{8,9}' ;;
    email)      echo '[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}' ;;
    iban)       echo 'NL[0-9]{2}[A-Z]{4}[0-9]{10}' ;;
    phone)      echo '(\+31|0031|0)[-. ]?6[-. ]?[0-9]{8}' ;;
    postcode)   echo '[1-9][0-9]{3} ?[A-Z]{2}' ;;
    creditcard) echo '[0-9]{13,16}' ;;
    fieldkey)   echo '(?i)(bsn|burgerservicenummer|geboortedatum|voornaam|achternaam|geslachtsnaam|adres|woonplaats|paspoort|rijbewijs|identiteitsbewijs|documentnummer)' ;;
  esac
}

TMP="$(mktemp)"
trap 'rm -f "${TMP}"' EXIT

# shellcheck disable=SC2016  # jq program: $s is jq syntax, must not shell-expand
JQ_TSV='.data.result[] as $s | $s.values[]
        | [($s.stream.namespace // "-"),
           ($s.stream.app // $s.stream.service_name // "-"),
           ($s.stream.pod // "-"),
           .[1]] | @tsv'

for cat in ${CATS}; do
  rx="$(filter_for "${cat}")"
  q="${QUERY} |~ ${BT}${rx}${BT}"
  echo "scanning category=${cat}"

  cursor="${START_NS}"
  pages=0
  raw=0
  while [[ "${cursor}" -lt "${END_NS}" ]]; do
    code="$(curl -sS -o "${TMP}" -w '%{http_code}' -G "${ENDPOINT}" \
      --data-urlencode "query=${q}" \
      --data-urlencode "start=${cursor}" \
      --data-urlencode "end=${END_NS}" \
      --data-urlencode "limit=${LIMIT}" \
      --data-urlencode "direction=forward")"

    if [[ "${code}" != "200" ]]; then
      echo "ERROR: query_range HTTP ${code} (cat=${cat}): $(head -c 300 "${TMP}")" >&2
      exit 1
    fi

    n="$(jq -r '[.data.result[]?.values[]?] | length' "${TMP}")"
    if [[ "${n}" -eq 0 ]]; then
      break
    fi

    # candidate lines -> validate + mask -> append masked findings
    jq -r "${JQ_TSV}" "${TMP}" | awk -v cat="${cat}" -f /scripts/classify.awk >> "${FINDINGS}"

    maxts="$(jq -r '.data.result[]?.values[]?[0]' "${TMP}" | sort | tail -1)"
    raw=$(( raw + n ))
    pages=$(( pages + 1 ))

    if [[ "${n}" -lt "${LIMIT}" ]]; then
      break
    fi
    cursor=$(( maxts + 1 ))
  done
  echo "  candidate lines scanned=${raw} pages=${pages}"
done

# ---- build masked report ----------------------------------------------------
{
  echo "Loki PII scan report"
  echo "selector: ${QUERY}"
  echo "window_ns: ${START_NS} .. ${END_NS}"
  echo "note: counts are VALIDATED matches (BSN 11-proef, IBAN mod-97, Luhn);"
  echo "      postcode/phone/fieldkey are regex-confirmed and may include some"
  echo "      false positives. All samples are MASKED."
  echo
  echo "== totals per category =="
  cut -f1 "${FINDINGS}" | sort | uniq -c | sort -rn
  echo
  echo "== matches per category + namespace =="
  cut -f1,2 "${FINDINGS}" | sort | uniq -c | sort -rn
  echo
  echo "== top locations (category / namespace / app / pod) =="
  cut -f1,2,3,4 "${FINDINGS}" | sort | uniq -c | sort -rn | head -40
  echo
  echo "== masked samples (up to 10 distinct per category) =="
  for cat in ${CATS}; do
    echo "--- ${cat} ---"
    awk -F'\t' -v c="${cat}" '$1==c{print $5}' "${FINDINGS}" | sort | uniq -c | sort -rn | head -10
  done
} > "${REPORT}"

echo
echo "===== SUMMARY (counts only; masked detail in ${REPORT}) ====="
echo "== totals per category =="
cut -f1 "${FINDINGS}" | sort | uniq -c | sort -rn
echo "== per category + namespace =="
cut -f1,2 "${FINDINGS}" | sort | uniq -c | sort -rn
echo "DONE report=${REPORT} findings=${FINDINGS}"
