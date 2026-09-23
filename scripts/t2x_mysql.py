"""Read-only client + account-id resolver for the T2X reference_data MySQL.

The manual_* `account_id` is derived from `reference_data.account_exchange.id`
with a hardcoded '001' sub-account suffix (e.g. MOON@BINANCE has id 1 -> '1001'),
which matches the account id the position service keys balances on.

Cred convention mirrors sync_accounts.py: T2X_RO_MYSQL_* env vars first, else
the `# t2x-ro-mysql` block in .env (keys ABOVE the marker; lookback-window parse).
"""
from __future__ import annotations
import os
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENV = REPO / ".env"

_ACCOUNT_SUFFIX = "001"  # hardcoded sub-account suffix for now


def load_creds() -> dict[str, str]:
    """Env vars (T2X_RO_MYSQL_*) take precedence; `# t2x-ro-mysql` .env block fallback."""
    env_creds = {
        k: os.environ[f"T2X_RO_MYSQL_{k.upper()}"]
        for k in ("host", "username", "password")
        if f"T2X_RO_MYSQL_{k.upper()}" in os.environ
    }
    if all(k in env_creds for k in ("host", "username", "password")):
        return env_creds

    if not ENV.exists():
        raise FileNotFoundError(
            f".env not found at {ENV} and T2X_RO_MYSQL_* env vars are incomplete"
        )

    lines = ENV.read_text(encoding="utf-8", errors="replace").splitlines()
    creds: dict[str, str] = {}
    for i, ln in enumerate(lines):
        if "t2x-ro-mysql" in ln.lower():
            for j in range(max(0, i - 5), min(len(lines), i + 3)):
                s = lines[j].strip()
                if not s or s.startswith("#"):
                    continue
                if ":" in s:
                    k, _, v = s.partition(":")
                    creds[k.strip().lower()] = v.strip()
            break
    if not all(k in creds for k in ("username", "password", "host")):
        raise RuntimeError("t2x-ro-mysql credentials missing in .env")
    return creds


def connect():
    """Open a pymysql connection to reference_data and pin the session READ-ONLY.

    Creds are the T2X read-only user; the session is additionally forced
    read-only client-side so this service can never write to reference_data.
    """
    import pymysql
    c = load_creds()
    conn = pymysql.connect(
        host=c["host"],
        user=c["username"],
        password=c["password"],
        database="reference_data",
        connect_timeout=15,
    )
    with conn.cursor() as cur:
        cur.execute("SET SESSION TRANSACTION READ ONLY")
    return conn


def account_exchange_id(cur, name: str) -> int | None:
    """reference_data.account_exchange.name -> id (active only). None if unknown."""
    if not name:
        return None
    cur.execute(
        "SELECT id FROM account_exchange "
        "WHERE name = %s AND deletedAt IS NULL "
        "ORDER BY id LIMIT 1",
        (name,),
    )
    row = cur.fetchone()
    return int(row[0]) if row else None


def resolve_account_id(cur, name: str) -> str | None:
    """Account NAME -> manual_* account_id string = account_exchange.id + '001'.

    e.g. 'MOON@BINANCE' (id 1) -> '1001'. None if the name is not an active
    account_exchange row (wallet/broker/bank accounts are not resolved yet).
    """
    ex_id = account_exchange_id(cur, name)
    if ex_id is None:
        return None
    return f"{ex_id}{_ACCOUNT_SUFFIX}"
