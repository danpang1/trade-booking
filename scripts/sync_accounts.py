"""Sync the account reference lists from MySQL → JSON file.

Source : sg-ro-mysql.internal.tokkalabs.com, `reference_data.account_exchange`,
         `account_wallet`, `account_broker`
Target : trade-booking/public/refdata/accounts.json
Filter : deletedAt IS NULL AND (status IS NULL OR status='ACTIVE')
         AND (type IS NULL OR type NOT LIKE '%SHADOW%')

Produces one combined JSON with three keys so the React form can
populate its EXCHANGE / WALLET / BROKER pickers from a single fetch:

    { "exchange": [...], "wallet": [...], "broker": [...] }

Each row is { name, venue, portfolio } — same shape the form has been
consuming from the static src/data/accounts.js snapshot it replaces.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pymysql

REPO = Path(__file__).resolve().parents[1]
ENV = REPO / ".env"
OUT = REPO / "public" / "refdata" / "accounts.json"

# Per-table SELECT: each account_* table uses a different column for the
# venue label. Keep the output row shape uniform so the frontend doesn't
# care which table a row came from.
TABLES = [
    ("exchange", "account_exchange", "exchangeName"),
    ("wallet",   "account_wallet",   "walletType"),
    ("broker",   "account_broker",   "brokerName"),
]


def _load_mysql_creds() -> dict[str, str]:
    """Env vars (T2X_RO_MYSQL_*) take precedence; .env file parsed as fallback."""
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


def _fetch(cur, table: str, venue_col: str) -> list[dict]:
    cur.execute(
        f"SELECT name, {venue_col} AS venue, linkedPortfolioName AS portfolio "
        f"FROM {table} "
        f"WHERE deletedAt IS NULL AND (status IS NULL OR status='ACTIVE') "
        f"  AND (type IS NULL OR type NOT LIKE '%SHADOW%') "
        f"ORDER BY name"
    )
    return [
        {"name": r[0], "venue": r[1] or "", "portfolio": r[2] or ""}
        for r in cur.fetchall()
    ]


def main() -> None:
    creds = _load_mysql_creds()
    conn = pymysql.connect(
        host=creds["host"],
        user=creds["username"],
        password=creds["password"],
        database="reference_data",
        connect_timeout=15,
    )
    out: dict[str, list[dict]] = {}
    try:
        cur = conn.cursor()
        for key, table, venue_col in TABLES:
            out[key] = _fetch(cur, table, venue_col)
    finally:
        conn.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    totals = ", ".join(f"{k}={len(v)}" for k, v in out.items())
    print(f"wrote accounts -> {OUT} ({totals})")


if __name__ == "__main__":
    main()
