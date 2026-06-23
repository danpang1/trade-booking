# Venue (gateway) credentials — Vault-backed

Venue API keys for the snapshot streamers resolve through one loader,
`scripts/gw_creds.py`, keyed by **gateway account id**. Prod reads the key from
Vault (agent-inject sidecar); UAT / local dev fall back to env / `.env`. Adding
a new account is a one-liner at the call site plus a Vault secret and one helm
values line — no new parsing code.

## Where the key lives

One Vault KV path per account:

```
kv/trading/prod/gw/<account_id>       # logical path (KV v2 engine mounted at kv)
kv/data/trading/prod/gw/<account_id>  # read/API path — /data/ goes after the mount
```

Document shape (single account per path):

```json
{
  "account_id": 218001,
  "auth_key": "...",
  "auth_secret": "...",
  "exch_account_id": "MOON-TOKKA@BITSTAMP_SPOT",
  "exch_name": "BITSTAMP_SPOT",
  "extra_secrets": { "password": "" }
}
```

`extra_secrets.password` is an optional venue API password (empty for Bitstamp
v2 HMAC). It is parsed into `GwCreds.password` but unused by Bitstamp signing.

## Resolution precedence (first hit wins)

1. **Vault agent-injected file** — `/vault/secrets/gw_<account_id>.json`
   (`VAULT_SECRETS_DIR` overrides the dir; `VAULT_SECRET_PATH` a single explicit
   file). The KV v2 `{"data":…}` envelope is unwrapped automatically.
2. **Env vars** — `<ENV_PREFIX>_API_KEY` / `_API_SECRET` / `_API_PASSWORD`
   (a k8s `Secret`, or shell export). `ENV_PREFIX` defaults to `GW_<account_id>`.
3. **`.env` flat keys** (local dev) — caller-supplied names, defaulting to
   `<account_id>.API_KEY` / `<account_id>.API_SECRET`.

`find_gw_creds()` returns `None` on miss (streamers warn + self-skip so the
shared cron never breaks); `load_gw_creds()` raises for callers that can't
proceed without creds.

## How it's wired in k8s (prod)

Authenticated venues run in their **own** CronJob, isolated from the public
`venue-snapshots` cron (`scripts/snapshot_all.py`) so a Vault/credential failure
can't break the public-venue snapshots. Bitstamp's is `bitstamp-snapshots`
(`scripts/snapshot_bitstamp.py`). Vault is enabled **prod-only** via the overlay
`helm_values/cron/bitstamp-snapshots-prod.yaml` (UAT has no Vault role, so it
stays on env/`.env`). The chart's `helm/templates/cronjob.yaml` renders the
agent-inject annotations from `.Values.vault.*` (mirrors the deployment),
including `agent-pre-populate-only: "true"` — init-only, so the Job's pod
completes instead of hanging on a long-lived vault-agent sidecar.

## Adding a new account

1. **Vault** — write the gw document to `kv/trading/prod/gw/<new_id>`. The
   `vault-main-trading-prod` role's policy must allow reading it.
2. **helm** — add one line under `agentInjectSecrets.paths` in the relevant
   cron's prod overlay (e.g. `helm_values/cron/bitstamp-snapshots-prod.yaml`,
   or a new `<venue>-snapshots-prod.yaml` if it gets its own isolated cron):

   ```yaml
   gw_<new_id>.json: "kv/data/trading/prod/gw/<new_id>"
   ```

3. **Streamer** — load it:

   ```python
   import gw_creds

   creds = gw_creds.find_gw_creds(<new_id>, env_prefix="VENUE")
   if creds:
       key, secret = creds.key, creds.secret
       # creds.password / creds.exch_name / creds.exch_account_id also available
   ```

   Pass `dotenv_key` / `dotenv_secret` only for non-default `.env` names
   (Bitstamp does, to keep its legacy `MAIN.BITSTAMP_API_*` keys).
4. **Local / UAT dev** — add `<new_id>.API_KEY=…` / `<new_id>.API_SECRET=…` to
   `.env` (or export `VENUE_API_KEY` / `VENUE_API_SECRET`).

No changes to `gw_creds.py`.

## Current accounts

| account_id | venue    | streamers                                          | env_prefix | Vault path                     |
|-----------:|----------|----------------------------------------------------|------------|--------------------------------|
| 218001     | Bitstamp | `stream_bitstamp.py`, `stream_bitstamp_balance.py` | `BITSTAMP` | `kv/data/trading/prod/gw/218001` |
