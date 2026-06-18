#!/usr/bin/env bash
#
# measure.sh - estimate total ingested log bytes in the query window via the
# Loki index/volume API. Prints "ESTIMATED_BYTES=<n>" on stdout for the
# orchestrator to parse and size the /dump PVC.
#
set -euo pipefail

GATEWAY="${GATEWAY:?GATEWAY not set}"
QUERY="${QUERY:?QUERY not set}"
START_NS="${START_NS:?START_NS not set}"
END_NS="${END_NS:?END_NS not set}"

TMP="$(mktemp)"
trap 'rm -f "${TMP}"' EXIT

# index/volume returns an instant vector: result[].value = [ts, "<bytes>"]
code="$(curl -sS -o "${TMP}" -w '%{http_code}' -G "${GATEWAY}/loki/api/v1/index/volume" \
  --data-urlencode "query=${QUERY}" \
  --data-urlencode "start=${START_NS}" \
  --data-urlencode "end=${END_NS}" \
  --data-urlencode "limit=100000" \
  --data-urlencode "aggregateBy=series")"

if [[ "${code}" != "200" ]]; then
  echo "ERROR: index/volume HTTP ${code}: $(head -c 500 "${TMP}")" >&2
  exit 1
fi

# Byte totals stay well under 2^53, so jq numeric add is safe here.
bytes="$(jq -r '[.data.result[]?.value[1] | tonumber] | add // 0 | floor' "${TMP}")"

echo "ESTIMATED_BYTES=${bytes}"
