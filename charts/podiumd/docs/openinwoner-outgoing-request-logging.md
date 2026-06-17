# Open Inwoner — disabling outgoing/external request logging

**How to stop Open Inwoner logging outgoing HTTP requests — Dimpact**

| | |
|---|---|
| Status | Reference |
| Applies to | Open Inwoner v2.1.2 (PodiumD 4.7.x) |
| Related | `docs/upgrade-from-4.7.3-to-4.7.4.md` (Open Formulieren equivalent) |

---

## Why this is different from Open Formulieren

Open Formulieren has a **master switch** (`LOG_OUTGOING_REQUESTS=False`) that empties
the logging handlers and disables outgoing-request logging entirely — that is how
PodiumD 4.7.4 turns it off for Open Formulieren by default.

**Open Inwoner (v2.1.2) has no such switch.** Its `LOGGING` config wires two
handlers *unconditionally* on the `log_outgoing_requests` logger:

```python
# open_inwoner/conf/base.py (v2.1.2)
"log_outgoing_requests": {            # emit handler -> structured stdout logs
    "class": "open_inwoner.utils.logging.StructlogOutgoingRequestsHandler",
    "level": "DEBUG",
},
"save_outgoing_requests": {           # save handler -> database
    "class": "log_outgoing_requests.handlers.DatabaseOutgoingRequestsHandler",
    "level": "DEBUG",
},
# logger
"log_outgoing_requests": {
    "handlers": ["log_outgoing_requests", "save_outgoing_requests"],
    "level": "DEBUG",
    "propagate": True,
},
```

The only environment-configurable knob is `LOG_OUTGOING_REQUESTS_DB_SAVE`
(default `True`), which controls **only** the database-save handler. There is no
env var that removes the handlers, so outgoing-request logging cannot be switched
off *entirely* from the environment — you control the two handlers separately.

There are therefore two distinct things to consider:

1. **Database persistence** (the `save_outgoing_requests` handler) — this is the
   one that grows the DB and stores request/response data. Controllable.
2. **Emit to stdout** (the `log_outgoing_requests` handler) — logs at `DEBUG`.

---

## 1. Stop saving outgoing requests to the database (recommended)

This is the meaningful change — it stops DB growth and request/response data being
stored. Two ways, use **either**:

### a. Via Helm values (env, applies on restart)

```yaml
openinwoner:
  extraEnvVars:
    - name: LOG_OUTGOING_REQUESTS_DB_SAVE
      value: "False"
```

`helm upgrade` rolls the pods and they pick it up — no data migration, existing rows
are not deleted. Note this changes Open Inwoner's upstream default (`True`).

> PodiumD 4.7.4 deliberately leaves this at its default and does **not** set it in
> the shared `values.yaml`; apply the override above per gemeente if you want DB
> logging off for Open Inwoner.

### b. Via the Django admin (runtime, no restart)

The `django-log-outgoing-requests` library provides an
`OutgoingRequestsLogConfig` singleton. In the Open Inwoner admin:

*Admin → Log outgoing requests → Outgoing requests log configuration* → set
**Save to database** = **Never**.

The runtime toggle **overrides** the env var: `save_to_db` values are
`Use default` (follow `LOG_OUTGOING_REQUESTS_DB_SAVE`), `Always`, or `Never`.
If a gemeente previously set it to **Always**, the env override in (a) has no
effect until you set it back to **Use default** or **Never**.

---

## 2. The stdout emit handler

The `log_outgoing_requests` (emit) handler logs at `DEBUG`. At the normal Open
Inwoner application log level (`INFO`/`WARNING`), these `DEBUG` records are already
not emitted, so in practice no separate action is needed to keep them out of the
container logs — just don't run the app at `DEBUG`.

There is **no env var** to remove this handler. Fully disabling it would require an
upstream `LOGGING` change in Open Inwoner (e.g. a master `LOG_OUTGOING_REQUESTS`
switch like Open Formulieren has) — track/raise that with Maykin if needed.

---

## Summary

| Goal | Open Inwoner (v2.1.2) |
|---|---|
| Stop DB persistence | `LOG_OUTGOING_REQUESTS_DB_SAVE=False` (env) **or** admin `Save to database = Never` |
| Stop stdout emit | Not env-configurable; already silent unless app log level is `DEBUG` |
| Disable everything via one env switch | **Not possible** — no master switch (unlike Open Formulieren) |
