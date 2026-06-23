"""Gateway (venue API) credential resolution, keyed by account id.

One reusable loader for every venue account, so adding a new account is a
one-liner at the call site plus a Vault secret — no new parsing code. Mirrors
the trade-booking / binance_vip_loan_ltv convention of preferring the Vault-
agent-injected file in prod and falling back to env / .env for local dev.

Each account maps to a Vault KV path  kv/trading/prod/gw/<account_id>  holding a
single-account document:

    {
      "account_id": 218001,
      "auth_key": "...",
      "auth_secret": "...",
      "exch_account_id": "MOON-TOKKA@BITSTAMP_SPOT",
      "exch_name": "BITSTAMP_SPOT",
      "extra_secrets": {"password": ""}
    }

In k8s the Vault agent renders each path to its own file under VAULT_SECRETS_DIR
(default /vault/secrets), named gw_<account_id>.json. With the agent's `json`
default template the file is the already-unwrapped doc; a KV v2 {"data": …}
envelope is also tolerated.

Resolution precedence per account (first hit wins):
  1. Vault agent-injected file  <VAULT_SECRETS_DIR>/gw_<account_id>.json  (prod)
     — or a single explicit file via the VAULT_SECRET_PATH env override.
  2. Env vars  <ENV_PREFIX>_API_KEY / _API_SECRET / _API_PASSWORD  (k8s Secret).
  3. .env flat keys (local dev) — caller-supplied names, defaulting to
     <account_id>.API_KEY / <account_id>.API_SECRET.

See docs/vault-credentials.md for the add-an-account recipe and the k8s
helm wiring (helm_values/cron/bitstamp-snapshots-prod.yaml + cronjob template).
"""
from __future__ import annotations

import json
import os
from collections import namedtuple
from pathlib import Path

# .env lives at the repo root (parent of this scripts/ dir).
ENV = Path(__file__).resolve().parents[1] / ".env"

# Field aliases tolerated in the Vault doc, in priority order — so a shape drift
# between gateway accounts (auth_key vs api_key vs ak) doesn't break us.
_KEY_FIELDS = ("auth_key", "api_key", "API_KEY", "apikey", "APIKEY", "ak", "key")
_SECRET_FIELDS = ("auth_secret", "api_secret", "API_SECRET", "secret",
                  "SECRET", "sk")

GwCreds = namedtuple(
    "GwCreds",
    "account_id key secret password exch_account_id exch_name",
)


def _vault_dirs() -> list[Path]:
    """Vault agent-inject dirs. VAULT_SECRETS_DIR overrides; else plural then
    singular default mount."""
    override = os.environ.get("VAULT_SECRETS_DIR")
    if override:
        return [Path(override)]
    return [Path("/vault/secrets"), Path("/vault/secret")]


def _pick(root: dict, fields: tuple[str, ...]) -> str | None:
    return next((str(root[f]) for f in fields if root.get(f)), None)


def _creds_from_root(account_id: int, root: object) -> GwCreds | None:
    if not isinstance(root, dict):
        return None
    key = _pick(root, _KEY_FIELDS)
    secret = _pick(root, _SECRET_FIELDS)
    if not (key and secret):
        return None
    extra = root.get("extra_secrets")
    password = ""
    if isinstance(extra, dict) and extra.get("password"):
        password = str(extra["password"])
    return GwCreds(
        account_id=root.get("account_id", account_id),
        key=key,
        secret=secret,
        password=password,
        exch_account_id=root.get("exch_account_id"),
        exch_name=root.get("exch_name"),
    )


def _from_vault(account_id: int) -> GwCreds | None:
    """Read creds from the Vault agent-injected file for this account, if any.

    Tries VAULT_SECRET_PATH (full override) first, then gw_<account_id>.json
    under each VAULT_SECRETS_DIR candidate. Unwraps the KV v2 "data" envelope.
    """
    candidates: list[Path] = []
    override = os.environ.get("VAULT_SECRET_PATH")
    if override:
        candidates.append(Path(override))
    for d in _vault_dirs():
        candidates.append(d / f"gw_{account_id}.json")

    for path in candidates:
        if not path.exists():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        roots = [doc]
        if isinstance(doc, dict) and isinstance(doc.get("data"), dict):
            roots.append(doc["data"])
        for root in roots:
            hit = _creds_from_root(account_id, root)
            if hit:
                return hit
    return None


def _from_env(account_id: int, env_prefix: str) -> GwCreds | None:
    key = os.environ.get(f"{env_prefix}_API_KEY")
    secret = os.environ.get(f"{env_prefix}_API_SECRET")
    if key and secret:
        return GwCreds(account_id, key, secret,
                       os.environ.get(f"{env_prefix}_API_PASSWORD", ""),
                       None, None)
    return None


def _read_dotenv() -> dict[str, str]:
    if not ENV.exists():
        return {}
    kv = {}
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        kv[k.strip()] = v.strip()
    return kv


def _from_dotenv(account_id: int, dotenv_key: str,
                 dotenv_secret: str) -> GwCreds | None:
    kv = _read_dotenv()
    key = kv.get(dotenv_key)
    secret = kv.get(dotenv_secret)
    if key and secret:
        return GwCreds(account_id, key, secret, "", None, None)
    return None


def find_gw_creds(account_id: int, *, env_prefix: str | None = None,
                  dotenv_key: str | None = None,
                  dotenv_secret: str | None = None) -> GwCreds | None:
    """Resolve gateway creds for one account by precedence. None on miss.

    account_id   the gw account id; selects Vault file gw_<account_id>.json.
    env_prefix   env-var prefix for the k8s-Secret fallback, e.g. "BITSTAMP"
                 -> BITSTAMP_API_KEY / _API_SECRET. Defaults to GW_<account_id>.
    dotenv_key / dotenv_secret
                 flat .env key names for local dev. Default to
                 "<account_id>.API_KEY" / "<account_id>.API_SECRET".
    """
    env_prefix = env_prefix or f"GW_{account_id}"
    dotenv_key = dotenv_key or f"{account_id}.API_KEY"
    dotenv_secret = dotenv_secret or f"{account_id}.API_SECRET"
    for source in (
        lambda: _from_vault(account_id),
        lambda: _from_env(account_id, env_prefix),
        lambda: _from_dotenv(account_id, dotenv_key, dotenv_secret),
    ):
        hit = source()
        if hit:
            return hit
    return None


def load_gw_creds(account_id: int, **kwargs) -> GwCreds:
    """Like find_gw_creds but raises RuntimeError on miss (for callers that
    cannot proceed without creds)."""
    hit = find_gw_creds(account_id, **kwargs)
    if hit:
        return hit
    env_prefix = kwargs.get("env_prefix") or f"GW_{account_id}"
    dirs = ", ".join(str(d / f"gw_{account_id}.json") for d in _vault_dirs())
    raise RuntimeError(
        f"gw creds not found for account {account_id}: no Vault file "
        f"({dirs}), no {env_prefix}_API_KEY / {env_prefix}_API_SECRET env "
        f"vars, and no matching keys in {ENV}"
    )
