# loki-pii-scan

One-off Dutch-PII (AVG/GDPR) sweep of Loki logs (`aks-blue-ontw-dim1`, ns
`monitoring`). Runs in-cluster, filters server-side, validates + **masks**
locally, and writes a masked report to a PVC that is snapshotted to Azure.

## What it detects

| Category     | How it's found                            | Validation (cuts false positives) |
|--------------|-------------------------------------------|-----------------------------------|
| `bsn`        | 8–9 digit runs                            | **11-proef / elfproef**           |
| `iban`       | `NL##AAAA##########`                       | **ISO 7064 mod-97**               |
| `creditcard` | 13–16 digit runs                          | **Luhn**                          |
| `email`      | RFC-ish address regex                     | regex-confirmed                   |
| `phone`      | NL mobile `+31/0031/0 6 ########`          | regex-confirmed                   |
| `postcode`   | NL `#### AA`                               | regex-confirmed (some FPs)        |
| `fieldkey`   | JSON/kv keys: `bsn`, `geboortedatum`, `adres`, `voornaam`, `achternaam`, `paspoort`, `rijbewijs`, `documentnummer`, ... | key+delimiter present |

Every reported sample is masked, e.g. `11****3`, `a***@example.nl`,
`NL**ABNA****4300`, `06*****78`, `************1111`, `adres=***`.

## Run

```bash
./loki-pii-scan.sh
```

Live progress (per-category candidate counts only — no PII):

```bash
kubectl --context aks-blue-ontw-dim1 -n monitoring logs -f job/loki-pii-scan
```

The job prints a **counts-only** summary at the end. The full masked report
(`/report/pii-report.txt` + `/report/findings.tsv`) stays on the PVC and is
snapshotted.

## Get the masked report off the PVC

Spin a throwaway pod that mounts the PVC, then `kubectl cp`:

```bash
kubectl --context aks-blue-ontw-dim1 -n monitoring run pii-fetch --restart=Never \
  --image=acrprodmgmt.azurecr.io/k8s:1.34.7 \
  --overrides='{"spec":{"containers":[{"name":"c","image":"acrprodmgmt.azurecr.io/k8s:1.34.7","command":["sleep","3600"],"volumeMounts":[{"name":"r","mountPath":"/report"}]}],"volumes":[{"name":"r","persistentVolumeClaim":{"claimName":"loki-pii-report"}}]}}' \
  --command -- sleep 3600
kubectl --context aks-blue-ontw-dim1 -n monitoring cp pii-fetch:/report ./pii-report
kubectl --context aks-blue-ontw-dim1 -n monitoring delete pod pii-fetch
```

(The Azure disk snapshot `loki-pii-report-snapshot` is the durable copy.)

## How it works

- Per category, a LogQL line filter (`{namespace=~".+"} |~ \`<regex>\``) runs
  server-side so **only candidate lines transfer**, not the whole log volume.
- Candidate lines are reshaped to `ns / app / pod / line` (jq) and piped to
  `classify.awk`, which re-validates (checksums) and emits **masked** records.
- Counts + masked samples are aggregated into the report.
- Window = last **30d** (Loki retention). Base image
  `acrprodmgmt.azurecr.io/k8s:1.34.7` (bash+curl+jq+awk) — internal ACR, no
  public egress.

## Caveats — read before acting on results

- **Names & free-text addresses** are NOT reliably regex-detectable. They are
  caught only when they appear under a known key (`naam`, `adres`, ...) via
  `fieldkey`. True name detection needs NER/ML — out of scope. Treat absence of
  name findings as "not proven clean".
- **Other AVG special categories** (health, religion, ethnicity, union/criminal
  data) are free-text → not covered here. Manual review still needed.
- **False positives**: `postcode` can match strings like `4096 MB`; `phone` can
  match unrelated number groupings; `fieldkey` flags the key regardless of
  whether a real value follows. Triage the masked samples.
- **False negatives**: PII split across fields, base64/encoded, or non-standard
  formats won't match. This is a strong first pass, not a guarantee.
- **Loki read cost**: 7 categories = 7 filtered passes over 30d. Run off-peak;
  it only reads.
- **The report is sensitive** (a map of where PII leaks, even masked). The
  snapshot uses `deletionPolicy: Retain` — delete deliberately when done.

## Tuning

- Add/adjust keys in `classify.awk` (`fieldkey` regex) and the matching filter
  in `scan.sh` (`filter_for`).
- Narrow scope: change `QUERY` in `loki-pii-scan.sh` (e.g.
  `{namespace="zaakgericht"}`) or shrink the window via `LOOKBACK_DAYS`.

## Cleanup

```bash
kubectl --context aks-blue-ontw-dim1 -n monitoring delete \
  job/loki-pii-scan pvc/loki-pii-report \
  configmap/loki-pii-scripts configmap/loki-pii-env
# snapshot retained on purpose:
# kubectl ... delete volumesnapshot loki-pii-report-snapshot
```
