#!/usr/bin/env bash
#
# dump.sh - export every matching Loki stream in the window to a single
# gzip file at /dump/loki-all.jsonl.gz, paginating query_range forward.
#
# Output is concatenated gzip members (valid gzip) of JSONL records:
#   {"ts":"<ns>","line":"<log line>","labels":{...}}
#
# Nanosecond cursors are compared/sorted as STRINGS, never via jq tonumber,
# because ns-since-epoch (~1.78e18) exceeds jq's 2^53 double precision.
# All current ns values are 19 digits, so lexicographic == numeric order.
#
set -euo pipefail

GATEWAY="${GATEWAY:?GATEWAY not set}"
QUERY="${QUERY:?QUERY not set}"
START_NS="${START_NS:?START_NS not set}"
END_NS="${END_NS:?END_NS not set}"
LIMIT="${LIMIT:-5000}"

OUT="/dump/loki-all.jsonl.gz"
META="/dump/manifest.txt"
ENDPOINT="${GATEWAY}/loki/api/v1/query_range"

TMP="$(mktemp)"
trap 'rm -f "${TMP}"' EXIT

echo "dump start query=${QUERY} from=${START_NS} to=${END_NS} limit=${LIMIT}"

# Truncate output to an empty gzip member; subsequent batches append members.
: | gzip -c > "${OUT}"

cursor="${START_NS}"
batch=0
total=0

while [[ "${cursor}" -lt "${END_NS}" ]]; do
  code="$(curl -sS -o "${TMP}" -w '%{http_code}' -G "${ENDPOINT}" \
    --data-urlencode "query=${QUERY}" \
    --data-urlencode "start=${cursor}" \
    --data-urlencode "end=${END_NS}" \
    --data-urlencode "limit=${LIMIT}" \
    --data-urlencode "direction=forward")"

  if [[ "${code}" != "200" ]]; then
    echo "ERROR: query_range HTTP ${code}: $(head -c 500 "${TMP}")" >&2
    exit 1
  fi

  n="$(jq -r '[.data.result[]?.values[]?] | length' "${TMP}")"
  if [[ "${n}" -eq 0 ]]; then
    break
  fi

  jq -c '.data.result[] as $s | $s.values[] | {ts: .[0], line: .[1], labels: $s.stream}' "${TMP}" \
    | gzip -c >> "${OUT}"

  # Global max timestamp across all streams, as a string.
  maxts="$(jq -r '.data.result[]?.values[]?[0]' "${TMP}" | sort | tail -1)"

  total=$(( total + n ))
  batch=$(( batch + 1 ))
  echo "batch=${batch} entries=${n} total=${total} cursor=${maxts}"

  # Fewer than LIMIT means this forward window is exhausted to END_NS.
  if [[ "${n}" -lt "${LIMIT}" ]]; then
    break
  fi

  # Advance 1ns past the last entry. ns collisions at this precision are
  # negligible; a shared-ts boundary could drop overlapping lines (logcli
  # dedups; this trades that edge case for simplicity).
  cursor=$(( maxts + 1 ))
done

bytes="$(wc -c < "${OUT}")"
{
  echo "query=${QUERY}"
  echo "start_ns=${START_NS}"
  echo "end_ns=${END_NS}"
  echo "entries=${total}"
  echo "gz_bytes=${bytes}"
} > "${META}"

echo "DONE entries=${total} file=${OUT} gz_bytes=${bytes}"
