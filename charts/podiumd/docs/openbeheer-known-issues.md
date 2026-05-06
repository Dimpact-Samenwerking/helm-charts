# Open Beheer — known issues and configuration traps

## 1. Container restarts every ~80–90 min (uWSGI master missing)

### Symptom

`openbeheer-*` pods accumulate restarts at a steady cadence (5+ in 24h).
`kubectl describe pod` shows:

```
Last State:     Terminated
  Reason:       Error
  Exit Code:    30
```

Previous-container logs end with:

```
[pid: 1|app: 0|req: 1000/2000] ... GET /admin/ ... HTTP/1.1 200 ...
The work of process 1 is done. Seeya!
```

No OOMKill (exit 137), no SIGKILL (exit 143). Just a clean uWSGI shutdown after all workers have completed their `max-requests` quota.

### Root cause

The open-beheer 0.9.0 docker image launches uWSGI without `--master`:

```
uwsgi --http :8000 --http-keepalive --manage-script-name \
      --mount /=openbeheer.wsgi:application \
      --static-map /static=/app/static --static-map /media=/app/media \
      --chdir src --enable-threads --processes 2 --threads 2 \
      --post-buffering=8192 --buffer-size=65535
```

Without `--master`, uWSGI runs in *shared* mode: there is no master process supervising workers. When a worker hits its `UWSGI_MAX_REQUESTS` quota, it exits and is **not** respawned. Once all `--processes` workers have cycled, the parent uWSGI process has no children left and exits with code 30 (`UWSGI_END_CODE` / graceful SIGTERM equivalent). The container exits, kubelet restarts it.

Cadence math (PodiumD defaults in 4.7.0):

| Source | Value |
|---|---|
| Probes (liveness + readiness on `/admin/`, period 10s) | ~24 req/min |
| `UWSGI_PROCESSES` | 2 |
| `UWSGI_MAX_REQUESTS` per worker | 1000 |
| Total req before container exit | ~2000 |
| Time per cycle | ~83 min |

Other Maykin Django apps in PodiumD (`openzaak`, `openklant`, `openformulieren`, etc.) ship docker images that *do* invoke uWSGI with `--master`, so the same `max-requests` recycle pattern is invisible at the container level — workers are respawned in-place. open-beheer is the outlier.

### Fix (chart-level)

`helm-charts/charts/podiumd/values.yaml` under `openbeheer.settings.uwsgi`:

```yaml
openbeheer:
  settings:
    uwsgi:
      master: "1"            # <-- adds UWSGI_MASTER=1 → uwsgi runs with --master
      processes: "2"
      threads: "2"
      maxRequests: "50000"   # was 1000 — pure defense-in-depth
```

The openbeheer subchart's configmap template already has support for `master`:

```yaml
# charts/openbeheer/templates/configmap.yaml
{{- if .Values.settings.uwsgi.master }}
UWSGI_MASTER: "1"
{{- end }}
```

uWSGI converts the `UWSGI_MASTER=1` env var into the `--master` flag at startup. With `--master`, the master process owns the workers and respawns any that exit (max-requests, harakiri, signal). The container no longer cycles.

`maxRequests` is bumped from 1000 to 50000 as belt-and-suspenders — even with `--master` working correctly, recycling 2 workers every ~80 min is wasteful for a low-traffic dev component. 50000 means a worker cycles roughly every 35 hours of probe-only traffic.

### Verifying on a cluster

```bash
CTX=<your-aks-context>
NS=podiumd

# Confirm the env var is set
kubectl --context "$CTX" -n "$NS" get cm openbeheer -o jsonpath='{.data.UWSGI_MASTER}'
# Expect: "1"

# Confirm the running uwsgi has --master
kubectl --context "$CTX" -n "$NS" exec deploy/openbeheer -- ps aux | grep uwsgi | head -1
# Expect: ... --master ... in the cmdline

# Watch for restarts over 24h
kubectl --context "$CTX" -n "$NS" get pods -l app.kubernetes.io/name=openbeheer
# Expect: RESTARTS column stays at 0 (or only bumps on legitimate failures)
```

### Upstream remediation

Open the issue against the open-beheer image to add `--master` (and ideally `--lazy-apps` for safer worker init) to the default uwsgi cmdline. Once that lands, `UWSGI_MASTER=1` becomes redundant in PodiumD values.
