"""Hourly balance snapshots for the second RH-chain wallet (EVM_05, GME RFQ)
via GoldRush balances-at-block — same pattern as rh_goldrush_snaps."""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

import avgcost_db

REPO = Path(__file__).resolve().parent
ALLOWLIST = REPO / "rh05_token_map.json"

ACCOUNT_NAME = "WALLET_CRB_EVM_05_ROBINHOOD"
ACCOUNT_ID = 489
WALLET = "0xe93c3433ee34b4a0d6f3830bc05d625c6dd0da7d"
CHAIN = "robinhood-mainnet"
UA = {"User-Agent": "Mozilla/5.0"}


def _env(key):
    for line in (REPO / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return None


def _gr(url):
    for attempt in range(5):
        try:
            d = json.loads(urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=60).read())
            if d.get("error"):
                raise RuntimeError(d.get("error_message"))
            return d["data"]
        except Exception:
            if attempt == 4:
                raise
            time.sleep(3 * (attempt + 1))


def _block_before(dt):
    key = _env("GOLDRUSH_API_KEY")
    lo = (dt - timedelta(minutes=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    hi = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    items = _gr(f"https://api.covalenthq.com/v1/{CHAIN}/block_v2/"
                f"{lo}/{hi}/?key={key}")["items"]
    if not items:
        return None
    b = items[-1]
    return b["height"], datetime.strptime(b["signed_at"], "%Y-%m-%dT%H:%M:%SZ")


def _balances_at(height):
    key = _env("GOLDRUSH_API_KEY")
    tmap = {a.lower(): (s, int(d)) for a, (s, d) in
            json.loads(ALLOWLIST.read_text(encoding="utf-8")).items()}
    items = _gr(f"https://api.covalenthq.com/v1/{CHAIN}/address/{WALLET}/"
                f"historical_balances/?block-height={height}&key={key}")["items"]
    out = []
    for it in items:
        addr = str(it.get("contract_address") or "").lower()
        native = it.get("native_token")
        if not native and addr not in tmap:
            continue
        if not native:
            sym, dec = tmap[addr]
            sym = sym.upper()
        else:
            sym = str(it.get("contract_ticker_symbol") or "ETH").upper()
            dec = int(it.get("contract_decimals") or 18)
        val = int(it.get("balance") or 0)
        if val == 0:
            continue
        out.append((sym, D(val) / D(10) ** dec,
                    {"token_address": addr, "decimals": dec,
                     "value": str(val), "block": height}))
    return out


INSERT_SQL = """
INSERT INTO tq_hist_balance_mo (
    account_id, account_name, exch, instrument, instrument_type, side,
    total_qty, avail_qty, frozen_qty, instrument_mo, instrument_exch,
    sync_ts, update_ts, original_data, borrowed_qty, interest_qty
) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
-- idempotent: a re-run, an overlapping run, or two writers racing
-- must not double a balance. fetch_snaps SUMS rows sharing an hour
-- bucket (to fold WETH into ETH etc.), so a duplicate row does not
-- look like a duplicate on the board - it silently doubles the
-- position and fabricates a break. Backed by uniq_bal_mo_snap.
ON CONFLICT (account_name, sync_ts, instrument) DO NOTHING
"""


def ensure_snaps(t0, t1, max_hours=100000):
    conn = avgcost_db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT date_trunc('hour',
                                sync_ts + interval '5 minutes')
                FROM tq_hist_balance_mo
                WHERE account_name = %s AND sync_ts >= %s AND sync_ts < %s
            """, (ACCOUNT_NAME, t0 - timedelta(hours=1), t1))
            have = {r[0].replace(tzinfo=None) for r in cur.fetchall()}
        want = []
        h = t0.replace(minute=0, second=0, microsecond=0)
        while h + timedelta(hours=1) <= t1:
            boundary = h + timedelta(hours=1)
            if boundary not in have:
                want.append(boundary)
            h = boundary
        if len(want) > max_hours:
            want = want[-max_hours:]
        filled = 0
        for boundary in want:
            blk = _block_before(boundary)
            if not blk:
                continue
            height, signed = blk
            rows = _balances_at(height)
            if not rows:
                continue
            with conn.cursor() as cur:
                for sym, qty, raw in rows:
                    cur.execute(INSERT_SQL, (
                        ACCOUNT_ID, ACCOUNT_NAME, "ROBINHOOD",
                        f"{sym}@ROBINHOOD", "INST_TYPE_SPOT", "long",
                        qty, qty, 0, sym, sym, signed, signed,
                        json.dumps(raw), 0, 0))
            conn.commit()
            filled += 1
        return filled
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    days = float(sys.argv[1]) if len(sys.argv) > 1 else 10
    n = ensure_snaps(now - timedelta(days=days), now)
    print(f"filled {n} hourly snapshots")
