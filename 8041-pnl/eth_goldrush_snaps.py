"""Hourly balance snapshots for the ETH RFQ wallet via GoldRush, by block.

No streamer needed: for every hour bucket missing from UAT
tq_hist_balance_mo (account WALLET_CRB_EVM_04_ETHEREUM), resolve the last
block signed before the hour boundary (block_v2 datetime window) and pull the
wallet's balances at that block (historical_balances?block-height=). Rows are
written with sync_ts = the block's signed_at, so the recon's -5min hour
bucketing lands them on the correct hour. Self-healing: the recon builder
calls ensure_snaps() each run, which backfills any gap (including the first
run's multi-day history) and keeps up hourly thereafter — GoldRush is paid
per call, so only missing hours are fetched.

Token filter: the RFQ token-map allowlist (eth_token_map.json) + native ETH.
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

import avgcost_db

REPO = Path(__file__).resolve().parent
ALLOWLIST = REPO / "eth_token_map.json"

ACCOUNT_NAME = "WALLET_CRB_EVM_04_ETHEREUM"
ACCOUNT_ID = 391001
WALLET = "0x391af49b1793529f430c4b5918da6bb237306865"
CHAIN = "eth-mainnet"
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
    """(height, signed_at) of the last block signed in the 3 min before dt."""
    key = _env("GOLDRUSH_API_KEY")
    lo = (dt - timedelta(minutes=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    hi = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    items = _gr(f"https://api.covalenthq.com/v1/{CHAIN}/block_v2/"
                f"{lo}/{hi}/?key={key}")["items"]
    if not items:
        return None
    b = items[-1]
    return b["height"], datetime.strptime(
        b["signed_at"], "%Y-%m-%dT%H:%M:%SZ")


def _balances_at(height):
    key = _env("GOLDRUSH_API_KEY")
    tmap = {}
    if ALLOWLIST.exists():
        tmap = {a.lower(): (s, int(d)) for a, (s, d) in
                json.loads(ALLOWLIST.read_text(encoding="utf-8")).items()}
    items = _gr(f"https://api.covalenthq.com/v1/{CHAIN}/address/{WALLET}/"
                f"historical_balances/?block-height={height}&key={key}")["items"]
    out = []
    for it in items:
        addr = str(it.get("contract_address") or "").lower()
        native = it.get("native_token")
        if not native and tmap and addr not in tmap:
            continue
        # our token map is authoritative for symbol and decimals; GoldRush
        # metadata is the fallback only
        if not native and addr in tmap:
            sym, dec = tmap[addr]
            sym = sym.upper()
        else:
            sym = str(it.get("contract_ticker_symbol") or "?").upper()
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


def ensure_snaps(t0, t1, max_hours=200):
    """Backfill missing hourly snapshots in [t0, t1) (naive-UTC datetimes).
    Returns the number of hours filled."""
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
        # hour H's snapshot fires just before H+1:00
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
                        ACCOUNT_ID, ACCOUNT_NAME, "ETHEREUM",
                        f"{sym}@ETHEREUM_RFQ", "INST_TYPE_SPOT", "long",
                        qty, qty, 0, sym, sym, signed, signed,
                        json.dumps(raw), 0, 0))
            conn.commit()
            filled += 1
        return filled
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    n = ensure_snaps(now - timedelta(days=days), now)
    print(f"[{ACCOUNT_NAME}] filled {n} hourly snapshots "
          f"(looked back {days}d)")
