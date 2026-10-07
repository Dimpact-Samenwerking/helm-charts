# Frank!Gateway — deployment runbook

The step-by-step procedure for bringing Frank!Gateway up on an environment for
the first time, with its OpenBao vault, and the checks to repeat after every
later deploy. It says what to do and in which order; the reasons behind each
step are in the reference documents it links to.

Read [`frankgateway-BASICS.md`](frankgateway-BASICS.md) first if you have not
met the gateway before, and
[`frankgateway-openbao.md`](frankgateway-openbao.md) for anything about OpenBao
that this page does not explain.

> **Shortcut for OpenBao.** Steps 3, 4, the gateway token of step 5 and step
> 8 are automated by `scripts/openbao-activate.sh`, which also does the
> after-every-deploy checks. The one-sitting flow for SSC is in
> [`frankgateway-openbao-activation.md`](frankgateway-openbao-activation.md).
> This page stays the manual reference.

## Conventions

Every command names its target explicitly; never rely on the current
kube-context or `az` subscription.

| Placeholder | Meaning |
|---|---|
| `<ctx>` | kube-context of the cluster |
| `<ns>` | namespace of the PodiumD release (usually `podiumd`) |
| `<release>` | Helm release name, e.g. `podiumd` |
| `<kv>` | environment Key Vault (`kv-<env>-<gemeente>` for `ExternalsPodiumD` environments) |
| `<mount>` | OpenBao KV mount: `frankgateway.openbao.mount`, or `openbao.configuration.kvPath` (default `secret`) when that is empty |
| `<env>-<gemeente>` | environment name as the `ExternalsPodiumD` scripts expect it |

## Two decisions before you start

**How the environment is deployed.** Environments deployed from ADO
`ExternalsPodiumD` have scripts (`pipelines/scripts/openbao_bootstrap.py`,
`openbao_unseal.py`) for initialising and unsealing OpenBao; step 3 has a
variant for them. Any other deployment does the same work by hand.

**Which seal OpenBao uses.**

| Seal | After a pod restart | `openbao-unseal-key` holds |
|---|---|---|
| **Static** (`openbao.seal.static.key` set) | the pod unseals itself | the recovery key (break-glass only) |
| **Shamir** (no key set) | the pod stays sealed until someone unseals it; Frank!Gateway answers 503 on key-bearing routes meanwhile | the unseal key, needed after every restart |

The trade-offs are in
[§3.6 and §3.6.1](frankgateway-openbao.md#36-seal--init--unseal-model-shamir).
Decide before step 3: the initialisation differs, and switching an
initialised Shamir vault to the static seal later is a migration.

## Step 1 — Infrastructure, once per environment

Out-of-band, before any deploy (Terraform, base-infra, `infra.yml`):

1. **PostgreSQL:** database `openbao` with owning role `openbao-admin` on the
   shared Azure PostgreSQL server; its password in Key Vault (the pipeline
   substitutes `REP_OPENBAO_DB_PASSWORD_REP`).
2. **Key Vault items:** `openbao-unseal-key` and `openbao-root-token`, and for
   the static seal also `openbao-seal-key`. In `ExternalsPodiumD` they are in
   the `passwords` list of `keyvault.tfvars`, so the platform pipeline creates
   them; `openbao-unseal-key` and `openbao-root-token` hold a placeholder until
   step 3. Elsewhere, create them by hand with the same names.
3. **Identity:** user-assigned Managed Identity with a federated credential for
   ServiceAccount `openbao`; note its client-id.
4. **Route and certificate:** a Gateway/Ingress route to
   `<release>-openbao-active:8200` over plain HTTP, on the host you will put in
   `openbao.configuration.oidcUrl` (convention
   `<env>-openbao-admin.<gemeente>.nl`), with a certificate whose SAN covers
   that host.
5. **Images:** egress to `quay.io` and `docker.io` for the images pinned in
   `values.yaml`, or mirror them to your ACR and override the repositories
   ([§3.1](frankgateway-openbao.md#31-container-images)).

The detail behind each item is in
[§3 Requirements](frankgateway-openbao.md#3-requirements).

## Step 2 — Environment values

OpenBao, with the hosts, database host and client-id of the environment:

```yaml
openbao:
  enabled: true
  configuration:
    enabled: true
    oidcUrl: https://<env>-openbao-admin.<gemeente>.nl
    keycloak:
      url: https://<env>-keycloak.<gemeente>.nl
      realm: podiumd
  database:
    host: podiumd-<env>-pg.postgres.database.azure.com
    password: REP_OPENBAO_DB_PASSWORD_REP
  server:
    serviceAccount:
      annotations:
        azure.workload.identity/client-id: "<uami-client-id>"
```

For the static seal add:

```yaml
openbao:
  seal:
    static:
      key: "REP_OPENBAO_SEAL_KEY_REP"
```

Frank!Gateway itself:

```yaml
frankgateway:
  enabled: true
```

Leave the routes out for now; step 6 adds them. Turning on NetworkPolicies, TLS
on the inway or more replicas is covered in
[`frankgateway-traffic-classes.md`](frankgateway-traffic-classes.md#enabling-the-gateway).
The full list of OpenBao values is in
[§4](frankgateway-openbao.md#4-values-reference).

## Step 3 — Deploy and initialise OpenBao

A deployed OpenBao starts **uninitialised and sealed**, and its pods still
report Ready. A green deploy proves nothing about the vault until this step is
done. Pick the variant that matches your two decisions.

### 3a — `ExternalsPodiumD`, static seal

1. **Deploy** with the Applications pipeline. After the Helm deploy,
   `openbao_unseal.py` fails the run because the vault is not initialised yet.
   That red run is expected.
2. **Initialise:**

   ```bash
   python3 pipelines/scripts/openbao_bootstrap.py --env <env>-<gemeente>
   ```

   It refuses to run until the StatefulSet and `Secret/openbao-seal` exist,
   then initialises the running OpenBao with one recovery key, waits until every pod has unsealed
   itself, and shows the recovery key and root token **once**. Store them in
   Key Vault as `openbao-unseal-key` and `openbao-root-token`; the script
   checks the stored key before it finishes.
3. **Deploy again.** The post-deploy check now passes.

### 3b — `ExternalsPodiumD`, Shamir

1. **Initialise before the first deploy:**

   ```bash
   python3 pipelines/scripts/openbao_bootstrap.py --env <env>-<gemeente>
   ```

   Add `--chart-branch <branch>` when the environment deploys from a
   helm-charts branch, and `--dry-run` to see the plan first. The script shows
   the chart and images it will use and asks for confirmation, initialises the
   vault from a temporary pod, shows the unseal key and root token **once**,
   and waits until you have stored them as `openbao-unseal-key` and
   `openbao-root-token`. Never use `--reset-existing-vault` on a vault that
   holds anything: it destroys it.
2. **Deploy** with the Applications pipeline. It refuses to start while
   `openbao-unseal-key` is missing or still the placeholder, and unseals every
   pod after the Helm deploy.

### 3c — Any other deployment

1. **Deploy** (`helm dep build charts/podiumd` first if the sub-chart `.tgz`
   is not there). The schema Job creates the tables, the server starts sealed
   and uninitialised, and the `openbao-config` Job skips itself.
2. **Initialise and store**, straight into Key Vault, so neither value is left
   in scrollback or a file:

   ```bash
   INIT=$(kubectl --context <ctx> -n <ns> exec <release>-openbao-0 -- \
     bao operator init -key-shares=1 -key-threshold=1 -format=json)

   az keyvault secret set --vault-name <kv> --name openbao-unseal-key \
     --file <(jq -j '.unseal_keys_b64[0]' <<<"$INIT") --encoding utf-8 -o none
   az keyvault secret set --vault-name <kv> --name openbao-root-token \
     --file <(jq -j '.root_token' <<<"$INIT") --encoding utf-8 -o none

   for item in 'openbao-unseal-key:.unseal_keys_b64[0]' 'openbao-root-token:.root_token'; do
     [ "$(az keyvault secret show --vault-name <kv> --name "${item%%:*}" --query value -o tsv)" \
       = "$(jq -j "${item#*:}" <<<"$INIT")" ] && echo "${item%%:*}: stored" \
       || echo "${item%%:*}: MISMATCH, do not continue"
   done
   unset INIT
   ```

   Keep `INIT` until both lines say `stored`. **With the static seal**, use
   `-recovery-shares=1 -recovery-threshold=1` instead of the key-share flags
   and `.recovery_keys_b64[0]` instead of `.unseal_keys_b64[0]`; store it as
   `openbao-unseal-key` all the same.
3. **Unseal every pod** — Shamir only; with the static seal the vault is
   unsealed as soon as it is initialised. Use the loop in
   [Unseal (Shamir)](#unseal-shamir).

## Step 4 — Configure OpenBao

1. **Mint the config token.** It lets the `openbao-config` Job configure the
   vault without the root token:

   ```bash
   BAO_ROOT_TOKEN_FILE=<(az keyvault secret show --vault-name <kv> \
     --name openbao-root-token --query value -o tsv) \
   KUBE_CONTEXT=<ctx> NAMESPACE=<ns> ./charts/podiumd/scripts/openbao-mint-config-token.sh
   ```

   The script writes the scoped `podiumd-config-job` policy, mints an orphan
   periodic token and seeds it into `Secret/openbao-bootstrap-token`. Never
   seed the root token there.
2. **Deploy again**, or re-run only the `openbao-config` Job as in
   [After every deploy](#after-every-deploy). It enables kv-v2, writes the
   uploader policy, configures the Keycloak login and binds the
   `vault-uploaders` group.
3. **Check it configured:** `kubectl --context <ctx> -n <ns> logs
   job/openbao-config` must say it configured, not that it skipped.
4. **Give uploaders access:** add the people who will write secrets to the
   Keycloak group `vault-uploaders`, or create the role and group first if the
   realm runs with `skipRoles`/`skipGroups`
   ([§3.7](frankgateway-openbao.md#37-keycloak--oidc-integration)).

## Step 5 — Put the gateway's secrets in OpenBao

1. **Write the secrets**, logged in as a `vault-uploaders` member
   (`bao login -method=oidc`):

   | What | Path | Fields | How to write it |
   |---|---|---|---|
   | External-API keys | `<mount>/frankgateway` | `bag_api_key`, `kvk_api_key` | `bao kv put <mount>/frankgateway bag_api_key=@bag.txt kvk_api_key=@kvk.txt` |
   | Outbound client certificates | `<mount>/frankgateway/client-certs/<name>` | `cert`, `key` | [routes → client certificates](frankgateway-routes.md#client-certificates-from-openbao-outbound-mtls) |
   | Inbound consumers | `<mount>/frankgateway/consumers` | one field per consumer | [routes → consumer identities](frankgateway-routes.md#consumer-identities-from-openbao-inbound) |

   `@file` keeps the key off the command line; delete the files afterwards.
   `bao kv put` replaces every field of a path, so change one field later with
   `bao kv patch`.
2. **Mint the gateway's reader token** with the root token, store it in Key
   Vault, create its Secret and restart the gateways. Nothing automates this
   yet ([IN-3047](https://dimpact.atlassian.net/browse/IN-3047)):

   ```bash
   ROOT=$(az keyvault secret show --vault-name <kv> --name openbao-root-token \
     --query value -o tsv)
   READER=$(kubectl --context <ctx> -n <ns> exec -i <release>-openbao-0 -- sh -e <<EOS
   export BAO_ADDR=http://<release>-openbao-active:8200 BAO_TOKEN=$ROOT
   bao auth tune -max-lease-ttl=8760h token/ >&2
   bao policy write frankgateway-reader - >&2 <<'HCL'
   path "<mount>/data/frankgateway"   { capabilities = ["read"] }
   path "<mount>/data/frankgateway/*" { capabilities = ["read"] }
   HCL
   bao token create -orphan -policy=frankgateway-reader -ttl=8760h \
     -display-name=frankgateway-reader -field=token
   EOS
   )
   unset ROOT

   az keyvault secret set --vault-name <kv> --name frankgateway-openbao-token \
     --file <(printf '%s' "$READER") --encoding utf-8 -o none
   printf '%s' "$READER" | kubectl --context <ctx> -n <ns> create secret generic \
       frankgateway-openbao-token --from-file=token=/dev/stdin --dry-run=client -o yaml \
     | kubectl --context <ctx> -n <ns> apply -f -
   unset READER

   kubectl --context <ctx> -n <ns> rollout restart deployment \
     -l app.kubernetes.io/component=frankgateway
   ```

   - The policy needs **both** paths: the wildcard does not match
     `frankgateway` itself, where the API keys live, and a missing path reads
     as an opaque 503.
   - The token lasts one year. Note the date: re-minting it needs a root token
     again.
   - The Secret name and key must match `frankgateway.openbao.tokenSecret`
     (default `frankgateway-openbao-token`, key `token`).

Until both are done, every key-bearing route answers 503.

## Step 6 — Routes

The chart ships no routes. Copy the bodies the environment needs from
[`frankgateway-routes.md`](frankgateway-routes.md) into
`frankgateway.instances.<class>.routes` — BAG and KVK on the outway, BRP on
the internal class, one `inbound-<app>` per public hostname on the inway —
label each `managed-by: iac`, and deploy. Then point applications that used
`apiproxy` at `http://frankgateway-outway:9080/...`, and app-to-app calls at
`http://frankgateway-internal:9080/...`.

## Step 7 — Verify

All pods Running proves very little here; most faults leave every pod healthy.
Check each of these:

1. **OpenBao:** in every server pod `bao status` shows `Initialized true`,
   `Sealed false`; the external host answers
   `curl -sSf https://<env>-openbao-admin.<gemeente>.nl/v1/sys/health` over a
   valid certificate; an uploader can log in through Keycloak and write. The
   full list is
   [§6 Verification](frankgateway-openbao.md#6-verification).
2. **Seed Jobs:** `kubectl --context <ctx> -n <ns> get jobs` — every
   `frankgateway-<class>-seed` completed; its log names each route it applied.
3. **Gateways:** `kubectl --context <ctx> -n <ns> get pods -l
   app.kubernetes.io/component=frankgateway` — all Running, on every class.
4. **A real call** through a key-bearing route (BAG or KVK on the outway)
   reaches its upstream instead of answering 503.
5. **The negative cases**, before the environment goes live: an inway route
   with consumer checks answers 401 to a caller without a registered
   certificate, and with OpenBao stopped a key-bearing route answers 503, not
   401. Test every class, not one. Why these matter:
   [faults that are invisible from outside](frankgateway-traffic-classes.md#faults-that-are-invisible-from-outside).

## Step 8 — Revoke the root token

Only once step 7 passes, run the step 4 script again with `--revoke-root`:

```bash
BAO_ROOT_TOKEN_FILE=<(az keyvault secret show --vault-name <kv> \
  --name openbao-root-token --query value -o tsv) \
KUBE_CONTEXT=<ctx> NAMESPACE=<ns> ./charts/podiumd/scripts/openbao-mint-config-token.sh --revoke-root
```

It re-mints the config token, then asks for confirmation before revoking the
root token. Leave the dead token in `openbao-root-token` so the
item keeps its history. When a root token is needed again — to re-mint the
config or reader token — create one with `bao operator generate-root` and the
key in `openbao-unseal-key`, write it over `openbao-root-token`, and revoke it
again when done.

## After every deploy

1. **Unsealed?** Static seal: check that `bao status` shows `sealed: false` on
   every pod. Shamir through `ExternalsPodiumD`: the pipeline unsealed them;
   check the same. Shamir otherwise: unseal as below.
2. **Config Job ran?** When a deploy restarts the OpenBao pods, the
   `openbao-config` Job runs while they are still sealed, logs `skipping
   config; reconcile after unseal` and exits 0 — without renewing the config
   token, which then expires after 32 days. If the log says it skipped, run it
   again now the vault is unsealed:

   ```bash
   kubectl --context <ctx> -n <ns> logs job/openbao-config
   kubectl --context <ctx> -n <ns> delete job openbao-config --ignore-not-found
   helm template <release> <chart> --version <version> -n <ns> -f <values> \
       --show-only templates/openbao-config-job.yaml \
     | kubectl --context <ctx> -n <ns> create -f -
   kubectl --context <ctx> -n <ns> wait --for=condition=complete job/openbao-config --timeout=5m
   kubectl --context <ctx> -n <ns> logs job/openbao-config
   ```

   Render with the same chart version and values as the deploy. The Job is
   kept for 10 minutes after it finishes; once it is gone, skip the first
   `logs` and just run it.
3. **Seed Jobs completed**, as in step 7.

With Shamir, a pod that restarts **between** deploys — node drain, eviction,
OOMKill — stays sealed until someone unseals it. The pipeline only unseals
after a deploy.

### Unseal (Shamir)

```bash
KEY=$(az keyvault secret show --vault-name <kv> --name openbao-unseal-key \
  --query value -o tsv)
REPLICAS=$(kubectl --context <ctx> -n <ns> get statefulset <release>-openbao \
  -o jsonpath='{.spec.replicas}')
for i in $(seq 0 $((REPLICAS - 1))); do
  kubectl --context <ctx> -n <ns> exec -i <release>-openbao-$i -- \
    sh -c 'read -r k; bao operator unseal "$k" >/dev/null' <<<"$KEY"
  printf '<release>-openbao-%s sealed=' "$i"
  kubectl --context <ctx> -n <ns> exec <release>-openbao-$i -- \
    bao status -format=json | jq -r .sealed
done
unset KEY REPLICAS
```

Every line must end `sealed=false`. The key goes in over stdin, so it is not
recorded in the Kubernetes audit log.

## Tokens that expire

| Token | Lifetime | Renewed by | When it lapses |
|---|---|---|---|
| Config token (`openbao-bootstrap-token`) | 32-day period | CronJob `openbao-token-renewal` (weekly) and every `openbao-config` run that does not skip | the Job fails; re-mint as in step 4, with a new root token, or run `openbao-activate.sh` |
| Gateway reader token (`frankgateway-openbao-token`) | one year when minted as in step 5; 32-day period, renewed weekly by the CronJob, when minted by `openbao-activate.sh` | nothing for the step-5 token ([IN-3047](https://dimpact.atlassian.net/browse/IN-3047)) | every key-bearing route answers 503; re-mint as in step 5, or run `openbao-activate.sh --rotate-reader-token` |

## Related documents

- [`frankgateway-BASICS.md`](frankgateway-BASICS.md) — what Frank!Gateway is,
  what it needs, and what changes in the next release.
- [`frankgateway-openbao.md`](frankgateway-openbao.md) — the OpenBao
  reference: requirements, seal model, Keycloak wiring, security notes.
- [`frankgateway-traffic-classes.md`](frankgateway-traffic-classes.md) — the
  three gateway instances, their values and the faults to probe for.
- [`frankgateway-routes.md`](frankgateway-routes.md) — writing routes, client
  certificates and consumer identities.
