"""One-off/repair: backfill HL fills from ClickHouse production.execution.

HL's userFillsByTime API only retains the most recent ~10k fills, so any
multi-day ingest outage loses fills permanently on the venue side. ClickHouse
keeps everything: exchange 'hip-xyz-perp' (xyz builder-dex perps, raw_symbol
'xyz:NVDA') and 'hyperliquid-spot' (raw_symbol '@465' = SPCXD/USDC).
Timestamps are in MICROseconds. No fee column exists, so backfilled fills
carry fee 0 — the recon shows a small USDC residual equal to the unrecorded
fees on affected days (attributable, position quantities exact).

Usage: python hl_ch_backfill.py 2026-07-17 2026-07-28
Dedup against the store is by external_trade_id (HL tid == CH trade_id), so
overlapping edges are safe; ingest_leg refolds legs on back-dated inserts.
"""
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import avgcost_db
import robinhood_ch_source as R

USER = "0x45bef7096101ffe85c7e4fd0cfbfb3cb2bfa61e3"   # TRADING_06
HLF_ACCT = "TRADING_06@HYPERLIQUID_FUTURES"
HLS_ACCT = "TRADING_06@HYPERLIQUID_SPOT"
SPOT_PAIRS = {"@465": "SPCXD",
              # @107 = HYPE/USDC. Added 2026-08-03: 17 fills
              # ($44k turnover) were being refused as an unmapped
              # pair, leaving the 1.307 HYPE the venue reports on the
              # spot account with no book explanation at all.
              "@107": "HYPE"}


def ch(sql, tries=5):
    for i in range(tries):
        try:
            req = urllib.request.Request(R.CH_URL, data=sql.encode())
            return urllib.request.urlopen(req, timeout=240).read().decode()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(8)


def pull_day(day_us0, day_us1):
    q = f"""
    SELECT exchange, raw_symbol, trade_id, side, price, quantity,
           ts_exchange_event
    FROM production.execution
    PREWHERE ts_exchange_event >= {day_us0} AND ts_exchange_event < {day_us1}
    WHERE exchange IN ('hip-xyz-perp', 'hyperliquid-spot')
      AND user_id = '{USER}'
    FORMAT TSV
    """
    rows = []
    for line in ch(q).splitlines():
        if not line.strip():
            continue
        exch, sym, tid, side, px, qty, ts_us = line.split("\t")
        rows.append((exch, sym, tid, int(side), D(px), D(qty),
                     int(ts_us) // 1000))
    return rows


def main():
    d0 = datetime.strptime(sys.argv[1], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    d1 = datetime.strptime(sys.argv[2], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    conn = avgcost_db.connect()
    perp = defaultdict(list)
    spot = defaultdict(list)
    day = d0
    while day <= d1:
        us0 = int(day.timestamp() * 1_000_000)
        us1 = int((day + timedelta(days=1)).timestamp() * 1_000_000)
        rows = pull_day(us0, us1)
        print(f"[ch] {day:%Y-%m-%d}: {len(rows)} fills", flush=True)
        for exch, sym, tid, side, px, qty, ts_ms in rows:
            fill = {
                "external_trade_id": str(tid),
                "trade_date_ms": ts_ms,
                "signed_qty": qty * side,
                "price": px,
                "fee_amount": D("0"),
                "fee_asset": "USDC",
                "source": "clickhouse",
                "venue": "HYPERLIQUID",
            }
            if exch == "hip-xyz-perp":
                fill["base_asset"] = sym
                perp[sym].append(fill)
            elif sym in SPOT_PAIRS:
                fill["base_asset"] = SPOT_PAIRS[sym]
                spot[SPOT_PAIRS[sym]].append(fill)
            else:
                print(f"  !! unmapped spot pair {sym} tid {tid} — skipped")
        day += timedelta(days=1)

    total_ins = 0
    for coin, fills in sorted(perp.items()):
        leg = {"venue": "HYPERLIQUID", "account": HLF_ACCT,
               "instrument": f"{coin}-P/USD@HYPERLIQUID_FUTURES",
               "product": "PERP", "quote_asset": "USDC", "counterparty": None}
        ins, fresh, refold = avgcost_db.ingest_leg(conn, leg, fills)
        conn.commit()
        total_ins += ins
        print(f"[ingest] {leg['instrument']}: {ins} inserted "
              f"({len(fills)} pulled, {fresh} fresh)"
              + (f", refold: {refold}" if refold else ""), flush=True)
    for coin, fills in sorted(spot.items()):
        leg = {"venue": "HYPERLIQUID", "account": HLS_ACCT,
               "instrument": f"{coin}/USDC@HYPERLIQUID_SPOT",
               "product": "SPOT", "quote_asset": "USDC", "counterparty": None}
        ins, fresh, refold = avgcost_db.ingest_leg(conn, leg, fills)
        conn.commit()
        total_ins += ins
        print(f"[ingest] {leg['instrument']}: {ins} inserted "
              f"({len(fills)} pulled, {fresh} fresh)"
              + (f", refold: {refold}" if refold else ""), flush=True)
    print(f"TOTAL inserted: {total_ins}")
    conn.close()


if __name__ == "__main__":
    main()
