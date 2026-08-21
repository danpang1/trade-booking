"""Transfers + hourly snapshots for the plain-custody CRB EVM wallets.

WALLET_CRB_EVM_01_BSC / _02_ETHEREUM / _03_BSC hold inventory and move it
around; none of them trades (verified 2026-07-31: zero swap txs across their
whole history), so their recon identity is simply

    snapshot delta = transfers

Both sides come from GoldRush: transfers from transaction log events, hourly
balances from `historical_balances` at the last block before each hour
boundary (independent of the transfer stream, so the recon is a real control
rather than a tautology).

Token allowlists are ESSENTIAL here, not cosmetic: these wallets are targets
of address-poisoning campaigns — EVM_03 receives dust from lookalikes of its
real counterparty, and EVM_02 has ~17 impostor contracts posing as USDC/USDT.
Only the contracts listed below are real.

Usage:
  python evm_custody_wallets.py transfers [YYYY-MM-DD]
  python evm_custody_wallets.py snaps [YYYY-MM-DD]
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

import avgcost_db

REPO = Path(__file__).resolve().parent
TRANSFER_TOPIC = ("0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a"
                  "4df523b3ef")

BSC_TOKENS = {
    "0x55d398326f99059ff775485246999027b3197955": ("USDT", 18),
    "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": ("USDC", 18),
    "0x5b1910eaad6450e50f816082aa078c41f10c292f": ("TSLAB", 18),
}
ETH_TOKENS = {
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": ("USDC", 6),
    "0xdac17f958d2ee523a2206206994597c13d831ec7": ("USDT", 6),
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": ("WETH", 18),
}

WALLETS = {
    "WALLET_CRB_EVM_01_BSC": {
        "account_id": 449, "chain": "bsc-mainnet", "exch": "BSC",
        "address": "0xE71b2e6dDc88FFdECdcd0D750c57D0122AA586c2",
        "tokens": BSC_TOKENS, "native": "BNB",
    },
    "WALLET_CRB_EVM_02_ETHEREUM": {
        "account_id": 460, "chain": "eth-mainnet", "exch": "ETHEREUM",
        "address": "0x9f736F87E6293AC1Bd9142E257dbfAC8b7AcF1ae",
        "tokens": ETH_TOKENS, "native": "ETH",
    },
    "WALLET_CRB_EVM_03_BSC": {
        "account_id": 461, "chain": "bsc-mainnet", "exch": "BSC",
        "address": "0x42A95A3B8d2FF2d12f3c393De42c7288FC943325",
        "tokens": BSC_TOKENS, "native": "BNB",
    },
}


def _key():
    env = (REPO / ".env").read_text(encoding="utf-8", errors="replace")
    return re.search(r"GOLDRUSH_API_KEY\s*[:=]\s*(\S+)",
                     env).group(1).strip("\"'")


def _gr(path, chain):
    url = f"https://api.covalenthq.com/v1/{chain}/{path}"
    hdr = {"User-Agent": "tokka-mo", "Authorization": f"Bearer {_key()}"}
    for attempt in range(5):
        try:
            d = json.loads(urllib.request.urlopen(
                urllib.request.Request(url, headers=hdr), timeout=60).read())
            if d.get("error"):
                raise RuntimeError(d.get("error_message"))
            return d["data"]
        except Exception:
            if attempt == 4:
                raise
            time.sleep(3 * (attempt + 1))


# ── transfers ──────────────────────────────────────────────────────────
def sync_transfers(acct, since_dt):
    cfg = WALLETS[acct]
    addr = cfg["address"].lower()
    rows = []
    for page in range(6):
        d = _gr(f"address/{addr}/transactions_v3/page/{page}/", cfg["chain"])
        items = d.get("items") or []
        if not items:
            break
        stop = False
        for tx in items:
            ts = datetime.strptime(tx["block_signed_at"],
                                   "%Y-%m-%dT%H:%M:%SZ").replace(
                                       tzinfo=timezone.utc)
            if ts < since_dt:
                stop = True
                continue
            for lg in (tx.get("log_events") or []):
                tp = lg.get("raw_log_topics") or []
                if not tp or tp[0] != TRANSFER_TOPIC or len(tp) < 3:
                    continue
                caddr = str(lg.get("sender_address") or "").lower()
                if caddr not in cfg["tokens"]:
                    continue                    # spam / poisoning token
                sym, dec = cfg["tokens"][caddr]
                frm = "0x" + tp[1][-40:]
                to = "0x" + tp[2][-40:]
                sign = (1 if to.lower() == addr else 0) + \
                       (-1 if frm.lower() == addr else 0)
                if not sign:
                    continue
                amt = D(int(lg.get("raw_log_data") or "0x0", 16)) / D(10) ** dec
                if amt == 0:
                    continue
                rows.append({
                    "asset": sym, "qty": amt * sign, "event_time": ts,
                    "external_id": f"{tx['tx_hash'].lower()}:{sym}",
                    "type": "DEPOSIT" if sign > 0 else "WITHDRAWAL",
                    "raw": json.dumps({"tx": tx["tx_hash"],
                                       "chain": cfg["chain"]})})
        if stop or not (d.get("links") or {}).get("prev"):
            break
    conn = avgcost_db.connect()
    n = 0
    try:
        with conn.cursor() as cur:
            for r in rows:
                cur.execute("""
                    INSERT INTO venue_transfers
                        (venue, account, asset, qty, transfer_type,
                         external_id, event_time, raw)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (venue, account, external_id, asset)
                    DO NOTHING
                """, (cfg["exch"], acct, r["asset"], str(r["qty"]),
                      r["type"], r["external_id"], r["event_time"], r["raw"]))
                n += cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return n, len(rows)


# ── hourly snapshots ───────────────────────────────────────────────────
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


def _block_before(chain, dt):
    lo = (dt - timedelta(minutes=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
    hi = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    items = _gr(f"block_v2/{lo}/{hi}/", chain)["items"]
    if not items:
        return None
    b = items[-1]
    return b["height"], datetime.strptime(b["signed_at"], "%Y-%m-%dT%H:%M:%SZ")


def ensure_snaps(acct, t0, t1, max_hours=100000, sparse=True):
    """Backfill hourly snapshots.

    sparse=True (default) snapshots only the hours that carry information for
    a dormant custody wallet: every hour a transfer landed, the hour either
    side of it (so the move is bounded by a before/after snapshot), and one
    daily anchor at the EOD cutoff. A quiet wallet renders 'no snap' for the
    rest, which is honest — and it avoids ~7.5k paid GoldRush calls per
    backfill that would only ever restate an unchanged balance.
    """
    cfg = WALLETS[acct]
    conn = avgcost_db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT date_trunc('hour',
                                sync_ts + interval '5 minutes')
                FROM tq_hist_balance_mo
                WHERE account_name = %s AND sync_ts >= %s AND sync_ts < %s
            """, (acct, t0 - timedelta(hours=1), t1))
            have = {r[0].replace(tzinfo=None) for r in cur.fetchall()}
            keep = None
            if sparse:
                cur.execute("""
                    SELECT DISTINCT date_trunc('hour', event_time)
                    FROM venue_transfers WHERE account = %s
                      AND event_time >= %s AND event_time < %s
                """, (acct, t0 - timedelta(days=1), t1))
                keep = set()
                for (hr,) in cur.fetchall():
                    hr = hr.replace(tzinfo=None)
                    # bucket H's snapshot fires at H+1; bound the move on
                    # both sides
                    for off in (0, 1, 2):
                        keep.add(hr + timedelta(hours=off))
        want = []
        h = t0.replace(minute=0, second=0, microsecond=0)
        while h + timedelta(hours=1) <= t1:
            boundary = h + timedelta(hours=1)
            daily_anchor = boundary.hour == 0        # EOD cutoff snapshot
            if boundary not in have and (keep is None or daily_anchor
                                         or boundary in keep):
                want.append(boundary)
            h = boundary
        filled = 0
        for boundary in want[-max_hours:]:
            blk = _block_before(cfg["chain"],
                                boundary.replace(tzinfo=timezone.utc))
            if not blk:
                continue
            height, signed = blk
            items = _gr(f"address/{cfg['address']}/historical_balances/"
                        f"?block-height={height}", cfg["chain"])["items"]
            rows = []
            for it in items:
                caddr = str(it.get("contract_address") or "").lower()
                if it.get("native_token"):
                    sym, dec = cfg["native"], 18
                elif caddr in cfg["tokens"]:
                    sym, dec = cfg["tokens"][caddr]
                else:
                    continue
                val = int(it.get("balance") or 0)
                if val == 0:
                    continue
                rows.append((sym, D(val) / D(10) ** dec,
                             {"token_address": caddr, "decimals": dec,
                              "value": str(val), "block": height}))
            if not rows:
                continue
            with conn.cursor() as cur:
                for sym, qty, raw in rows:
                    cur.execute(INSERT_SQL, (
                        cfg["account_id"], acct, cfg["exch"],
                        f"{sym}@{cfg['exch']}", "INST_TYPE_SPOT", "long",
                        qty, qty, 0, sym, sym, signed, signed,
                        json.dumps(raw), 0, 0))
            conn.commit()
            filled += 1
        return filled
    finally:
        conn.close()


if __name__ == "__main__":
    # --dense fills EVERY hour rather than transfer-hours + daily anchors.
    # The daily cycle uses it over a short window: history was densified to
    # ~99% on 2026-08-01, and a sparse tip would immediately start re-opening
    # the gaps that cost ~6,000 GoldRush calls to close. Over a 2-day window
    # that is ~144 hours across 3 wallets, most already stored and skipped.
    dense = "--dense" in sys.argv
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    mode = argv[0] if argv else "transfers"
    start = (datetime.strptime(argv[1], "%Y-%m-%d")
             if len(argv) > 1 else datetime(2026, 6, 9))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for acct in WALLETS:
        if mode == "transfers":
            n, seen = sync_transfers(acct, start.replace(tzinfo=timezone.utc))
            print(f"[{acct}] +{n} transfer rows ({seen} legs seen)",
                  flush=True)
        else:
            n = ensure_snaps(acct, start, now, sparse=not dense)
            print(f"[{acct}] filled {n} snapshot hours"
                  f"{' (dense)' if dense else ' (sparse)'}", flush=True)
    print("EVM_CUSTODY_DONE")
