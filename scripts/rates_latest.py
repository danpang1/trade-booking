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


def _load_credentials() -> dict[str, str]:
    """Parse the `# MYSQL TOKEN PRICE DB` block in .env (YAML-style
    `key:value` lines). Mirrors the parser in nxgen-mo-tools's
    mysql_rates.py — kept inline so this script has no cross-repo deps.
    Env vars MYSQL_TOKEN_PRICE_DB_{HOST,USERNAME,PASSWORD} take
    precedence for prod deploys."""
    env_creds = {
        k: os.environ[f"MYSQL_TOKEN_PRICE_DB_{k.upper()}"]
        for k in ("host", "username", "password")
        if f"MYSQL_TOKEN_PRICE_DB_{k.upper()}" in os.environ
    }
    if all(k in env_creds for k in ("host", "username", "password")):
        return env_creds
    if not ENV_PATH.exists():
        raise FileNotFoundError(f".env not found at {ENV_PATH}")
    creds: dict[str, str] = {}
    in_block = False
    for line in ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if "MYSQL TOKEN PRICE DB" in s.upper():
            in_block = True
            continue
        if not in_block:
            continue
        if not s or s.startswith("#"):
            if s.startswith("#") and "MYSQL" not in s.upper():
                break
            continue
        if ":" in s:
            k, _, v = s.partition(":")
            creds[k.strip().lower()] = v.strip()
    missing = [k for k in ("username", "password", "host") if k not in creds]
    if missing:
        raise RuntimeError(f"MySQL Token Price DB creds missing keys: {missing}")
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
