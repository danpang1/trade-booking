"""Self-healing Native top-up: ClickHouse execution fills the streamer's gaps.

stream_native_fills.py is the PRIMARY Native ingest (venue API, ~8 min
retention, 2-min poll). When it dies, fills are unreachable from the API
forever — it died 2026-07-30 09:51 and four days of QQQB trading (9k+ fills)
existed only in ClickHouse `production.execution` exchange='native-spot' (the
trading-team logger). This stage makes that loss self-healing: every cycle,
any CH fill whose TRANSACTION is not in the store gets ingested.

Why tx-level dedup is exactly right: the streamer's ids are
`tx_hash:tx_index`, the CH loader's are `tx:oid:px` — different strings for
the same fill, so id-level dedup CANNOT work and running both sources naively
double-books (the reason this was manual-only until 2026-08-03). But both
formats START with the tx hash, and streamer capture is binary per tx — if it
was alive it stored every fill of that tx. So: tx already stored (either
format) -> skip; tx unseen -> a genuine gap fill.

CH has no fee column, so healed fills carry fee 0 (same caveat as the June
union load — venue fees on Native are sub-dollar per day).

Back-dated inserts invalidate the leg's memoized fold, so every touched leg
is refolded.

  python native_ch_topup.py [--dry-run] [--days N]   (default: last 7 days)
"""
from __future__ import annotations

import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import avgcost_db as adb
import native_trades_source as nts

ACCOUNT = "TRADING_01@NATIVECORE"
VENUE = "NATIVE CORE"


def stored_txes(conn, since):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT external_trade_id FROM trades_spot_avgcost
            WHERE account = %s AND trade_date >= %s
        """, (ACCOUNT, since))
        return {r[0].split(":")[0].lower() for r in cur.fetchall()}


def main():
    dry = "--dry-run" in sys.argv
    days = int(sys.argv[sys.argv.index("--days") + 1]) \
        if "--days" in sys.argv else 7
    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_ms = int(since.timestamp() * 1000)

    conn = adb.connect()
    try:
        have = stored_txes(conn, since)
        gap = [f for f in nts.ch_fills().values()
               if f["trade_date_ms"] >= since_ms
               and f["external_trade_id"].split(":")[0].lower() not in have]
        gap.sort(key=lambda f: f["trade_date_ms"])
        # streamer staleness is the failure this heals — say it out loud
        with conn.cursor() as cur:
            cur.execute("SELECT max(trade_date) FROM trades_spot_avgcost "
                        "WHERE account = %s", (ACCOUNT,))
            newest = cur.fetchone()[0]
        age_h = ((datetime.now(timezone.utc) - newest).total_seconds() / 3600
                 if newest else 999)
        if age_h > 3:
            print(f"[native] WARNING: newest stored fill is {age_h:.1f}h old "
                  "— is stream_native_fills.py running?")
        if not gap:
            print(f"[native] CH top-up: store already covers every CH tx "
                  f"in the last {days}d")
            return
        by_sym = defaultdict(lambda: [0, D(0)])
        for f in gap:
            by_sym[f["base_asset"]][0] += 1
            by_sym[f["base_asset"]][1] += f["signed_qty"]
        print(f"[native] CH top-up: {len(gap)} fills missing from the store "
              f"({datetime.fromtimestamp(gap[0]['trade_date_ms'] / 1000, timezone.utc):%m-%d %H:%M}"
              f" .. {datetime.fromtimestamp(gap[-1]['trade_date_ms'] / 1000, timezone.utc):%m-%d %H:%M})")
        for sym, (n, q) in sorted(by_sym.items()):
            print(f"  {sym}: {n} fills, net qty {q:+,.3f}")
        if dry:
            print("  (dry run — nothing written)")
            return
        for sym in sorted(by_sym):
            inst = f"{sym}/USDT@NATIVECORE"
            leg = {"venue": VENUE, "account": ACCOUNT, "instrument": inst,
                   "product": "SPOT", "quote_asset": "USDT",
                   "counterparty": None}
            sf = [dict(f, venue=VENUE) for f in gap
                  if f["base_asset"] == sym]
            n = adb.ingest_leg(conn, leg, sf)
            t0 = time.time()
            rows, tip = adb.refold_leg(conn, inst)
            conn.commit()
            print(f"  {inst}: +{n} ingested, refold {rows} rows "
                  f"({time.time() - t0:.0f}s), tip qty {tip}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
