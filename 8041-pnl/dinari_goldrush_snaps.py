"""Hourly balance snapshots for the Dinari treasury wallet (HyperEVM).

TOKKA TREASURY - EVM - 01 - DINARI (0xb7c6...fd3c) has no official
tq_hist_balance feed, GoldRush's historical_balances returns 501 on
hyperevm-mainnet (frontier-tier chain), and the public HyperEVM RPC silently
ignores the block parameter on eth_call (non-archive) — so token history
cannot be read directly.

Instead, snaps are RECONSTRUCTED FORWARD FROM ZERO: the wallet is new
(first activity 2026-06-12), so balance at hour boundary B = sum of chain
transfers (venue_transfers, account TOKKA_TREASURY_EVM_01_DINARI) before B.
chain_transfers.sync() must therefore run FIRST. Rows are written to UAT
tq_hist_balance_mo with sync_ts = boundary - 1s so the recon's -5min hour
bucketing lands them on the correct hour.

Honesty notes: the hourly identity for this column ties by construction
(snaps derive from the same transfer stream) — the INDEPENDENT check is the
live GoldRush balance at the tip: ensure_snaps prints any drift between the
forward reconstruction and the live wallet. Known drift: the HyperEVM
'USDC' (0xb88339cb) moved ~0.9928 of balance WITHOUT Transfer events
(non-standard; hyperscan's own event-derived balance shows the same 0.9951
vs 0.0023 on-chain, found 2026-07-30) — dust, reported not repaired. Native
HYPE (~gas dust) is excluded: gas spend is not in the transfer stream and
would accumulate drift.
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
ALLOWLIST = REPO / "dinari_token_map.json"

ACCOUNT_NAME = "TOKKA_TREASURY_EVM_01_DINARI"
ACCOUNT_ID = 460590
WALLET = "0xb7c6a246c658814c5a879fbec61055ec9896fd3c"
CHAIN = "hyperevm-mainnet"
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


def _live_balances():
    """{SYM: Decimal qty} for allowlisted tokens, right now (LIVE anchor)."""
    key = _env("GOLDRUSH_API_KEY")
    tmap = {a.lower(): (s, int(d)) for a, (s, d) in
            json.loads(ALLOWLIST.read_text(encoding="utf-8")).items()}
    items = _gr(f"https://api.covalenthq.com/v1/{CHAIN}/address/{WALLET}/"
                f"balances_v2/?no-spam=true&key={key}")["items"]
    out = {}
    for it in items:
        addr = str(it.get("contract_address") or "").lower()
        if addr not in tmap:
            continue                     # native HYPE + spam excluded
        sym, dec = tmap[addr]
        out[sym.upper()] = D(int(it.get("balance") or 0)) / D(10) ** dec
    return out


def _all_transfers(conn):
    """[(event_time_naive_utc, SYM, signed qty)] for the account, ex-HYPE —
    the ENTIRE history (forward reconstruction starts from zero)."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT event_time, asset, qty FROM venue_transfers
            WHERE account = %s AND asset <> 'HYPE'
              AND COALESCE(transfer_type, '') <> 'SETTLEMENT_BOOKED'
            ORDER BY event_time
        """, (ACCOUNT_NAME,))
        return [(ts.astimezone(timezone.utc).replace(tzinfo=None),
                 a.upper(), D(str(q))) for ts, a, q in cur.fetchall()]


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
    """Reconstruct + insert missing hourly snapshots in [t0, t1) (naive-UTC).
    Returns the number of hours filled."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    t1 = min(t1, now)
    anchor = _live_balances()
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
        xfers = _all_transfers(conn)

        def bal_at(boundary):
            """forward from zero: sum of transfers BEFORE the boundary."""
            b = {}
            for ts, sym, q in xfers:
                if ts < boundary:
                    b[sym] = b.get(sym, D(0)) + q
            return b

        # tip check: forward reconstruction at 'now' vs the LIVE wallet —
        # any drift = missed transfers or non-standard token mechanics
        tip = bal_at(now)
        for sym in sorted(set(tip) | set(anchor)):
            diff = tip.get(sym, D(0)) - anchor.get(sym, D(0))
            if abs(diff) > D("0.000001"):
                print(f"[dinari-snaps] tip drift {sym}: reconstructed "
                      f"{tip.get(sym, D(0))} vs live {anchor.get(sym, D(0))} "
                      f"(diff {diff})")

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
            rows = [(sym, qty) for sym, qty in bal_at(boundary).items()
                    if qty != 0]
            if not rows:
                continue
            signed = boundary - timedelta(seconds=1)
            with conn.cursor() as cur:
                for sym, qty in rows:
                    cur.execute(INSERT_SQL, (
                        ACCOUNT_ID, ACCOUNT_NAME, "DINARI",
                        f"{sym}@DINARI", "INST_TYPE_SPOT", "long",
                        qty, qty, 0, sym, sym, signed, signed,
                        json.dumps({"reconstructed": True,
                                    "anchor_ts": now.isoformat()}), 0, 0))
            conn.commit()
            filled += 1
        return filled
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    days = float(sys.argv[1]) if len(sys.argv) > 1 else 6
    n = ensure_snaps(now - timedelta(days=days), now)
    print(f"filled {n} hourly snapshots")
