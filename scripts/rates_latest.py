"""Fetch the latest available USD rates from the MySQL token-price DB.

Walks back from today UTC up to 7 days, looking for the most recent
`price_token_new` snapshot. Mirrors the dedup rules used by
nxgen-mo-tools/scripts/pnl/mysql_rates.py:
    1. Prefer the canonical row where tokenAddress = 0x000…000
       (e.g. native BTC over BTC token clones).
    2. Otherwise pick the highest-price row (canonical asset usually
       has the largest market cap and price among same-ticker imposters).

Writes JSON: {"ok": true, "asOf": ISO, "cob": "YYYY-MM-DD",
              "source": "reference_data.price_token_new",
              "rates": { "BTC": 65000.0, ... }}.
Reads no stdin params (empty JSON object accepted).

Uses the t2x read-only MySQL credentials (T2X_RO_MYSQL_* / `# MYSQL RO`
.env block) — `price_token_new` is in the same `reference_data` schema as
the refdata tables, so no separate token-price DB credentials are needed.
"""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pymysql


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
NATIVE_TOKEN_ADDR = "0x0000000000000000000000000000000000000000"
WALKBACK_DAYS = 7


# Section markers that anchor the t2x read-only MySQL block in .env.
# Different scripts/.env templates in this repo have used different
# headers over time; price_token_new lives in the same `reference_data`
# schema as those creds, so any of these blocks works.
_RO_MARKERS = (
    "t2x-ro-mysql",
    "sg-ro-mysql",
    "mysql ro",
    "mysql read-only",
    "mysql token price",
)
_CRED_KEYS = ("host", "username", "password")


def _load_credentials() -> dict[str, str]:
    """Read the t2x read-only MySQL creds — the SAME credentials the
    refdata sync scripts use, since `price_token_new` lives in the same
    `reference_data` schema as the instrument/counterparty/portfolio
    tables. Env vars T2X_RO_MYSQL_{HOST,USERNAME,PASSWORD} take precedence
    for prod deploys; otherwise the .env block is parsed. The .env scan
    accepts every marker this repo has used (see _RO_MARKERS) and grabs
    the host/username/password trio from a window around the marker, so it
    works whether the keys sit above the marker (lookback convention used
    by sync_counterparties.py) or below it."""
    env_creds = {
        k: os.environ[f"T2X_RO_MYSQL_{k.upper()}"]
        for k in _CRED_KEYS
        if f"T2X_RO_MYSQL_{k.upper()}" in os.environ
    }
    if all(k in env_creds for k in _CRED_KEYS):
        return env_creds
    if not ENV_PATH.exists():
        raise FileNotFoundError(f".env not found at {ENV_PATH}")
    lines = ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    creds: dict[str, str] = {}
    for i, line in enumerate(lines):
        if not any(m in line.lower() for m in _RO_MARKERS):
            continue
        # Grab the trio from a window spanning the keys-above (lookback)
        # and keys-below conventions; first value found per key wins.
        for j in range(max(0, i - 5), min(len(lines), i + 5)):
            s = lines[j].strip()
            if not s or s.startswith("#") or ":" not in s:
                continue
            k, _, v = s.partition(":")
            key = k.strip().lower()
            if key in _CRED_KEYS:
                creds.setdefault(key, v.strip())
        if all(k in creds for k in _CRED_KEYS):
            break
    missing = [k for k in _CRED_KEYS if k not in creds]
    if missing:
        raise RuntimeError(f"MySQL RO credentials missing keys: {missing}")
    return creds


def _connect():
    c = _load_credentials()
    return pymysql.connect(
        host=c["host"],
        user=c["username"],
        password=c["password"],
        database="reference_data",
        connect_timeout=15,
        read_timeout=60,
    )


def _dedupe_rows(rows) -> dict[str, float]:
    """Group rows by uppercased symbol; pick canonical via zero-address
    preference then max-price tie-break."""
    grouped: dict[str, list[tuple[float, str | None]]] = {}
    for sym, price, token_addr in rows:
        if sym is None or price is None:
            continue
        try:
            p = float(price)
        except (TypeError, ValueError):
            continue
        if p <= 0:
            continue
        key = str(sym).strip().upper()
        if not key:
            continue
        ta = (token_addr or "").strip().lower() or None
        grouped.setdefault(key, []).append((p, ta))
    out: dict[str, float] = {}
    for sym, candidates in grouped.items():
        if len(candidates) == 1:
            out[sym] = candidates[0][0]
            continue
        native = [c for c in candidates if c[1] == NATIVE_TOKEN_ADDR]
        pool = native if native else candidates
        pool.sort(key=lambda c: -c[0])
        out[sym] = pool[0][0]
    return out


def _fetch_for_cob(cur, cob_date) -> tuple[datetime, dict[str, float]] | None:
    target_ts = datetime.combine(cob_date + timedelta(days=1), datetime.min.time())
    cur.execute(
        "SELECT symbol, price, tokenAddress "
        "  FROM price_token_new "
        " WHERE quote = 'USD' AND targetTimestamp = %s",
        (target_ts,),
    )
    rates = _dedupe_rows(cur.fetchall())
    if not rates:
        return None
    return target_ts, rates


def main() -> int:
    # stdin accepted for forward-compat but ignored in v1.
    sys.stdin.read()
    try:
        conn = _connect()
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB connect failed", "detail": str(e)}))
        return 5
    today = datetime.utcnow().date()
    try:
        with conn.cursor() as cur:
            for back in range(WALKBACK_DAYS + 1):
                cob = today - timedelta(days=back)
                hit = _fetch_for_cob(cur, cob)
                if hit:
                    target_ts, rates = hit
                    print(json.dumps({
                        "ok": True,
                        "asOf": target_ts.replace(tzinfo=timezone.utc).isoformat(),
                        "cob": cob.isoformat(),
                        "source": "reference_data.price_token_new",
                        "rates": rates,
                    }))
                    return 0
        print(json.dumps({
            "ok": False,
            "error": f"No rates found in the last {WALKBACK_DAYS + 1} days",
        }))
        return 4
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB query failed", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
