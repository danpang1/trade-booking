"""Repair: re-pull ClickHouse rfq_fill for ROBINHOOD from a given date and
diff-ingest anything the store lacks (late-arriving CH rows land days behind
the incremental watermark and are otherwise never fetched).

Usage: python rh_ch_repair.py 2026-07-11
Dedup is by external id '{tx}:{TICKER}'; ingest_leg refolds back-dated legs.
"""
import sys
from datetime import datetime, timezone

import avgcost_db
import robinhood_ch_source

RH_ACCT = "WALLET_CRB_EVM_02_ROBINHOOD"


def main():
    d0 = datetime.strptime(sys.argv[1], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    since_ms = int(d0.timestamp() * 1000)
    print(f"[repair] pulling CH rfq_fill since {d0:%Y-%m-%d} ...", flush=True)
    events = robinhood_ch_source.ch_rfq_events(since_ms)
    total = sum(len(v) for v in events.values())
    print(f"[repair] {total} CH fills across {len(events)} tickers", flush=True)
    conn = avgcost_db.connect()
    grand = 0
    for ticker, fills in sorted(events.items()):
        for f in fills:
            f.setdefault("venue", "ROBINHOOD")
        leg = {"venue": "ROBINHOOD", "account": RH_ACCT,
               "instrument": ticker + "/USDG@ROBINHOOD", "product": "SPOT",
               "quote_asset": "USDG", "counterparty": None}
        ins, fresh, refold = avgcost_db.ingest_leg(conn, leg, fills)
        conn.commit()
        grand += ins
        if ins:
            print(f"[repair] {leg['instrument']}: +{ins}"
                  + (f" (refold: {refold})" if refold else ""), flush=True)
    print(f"[repair] TOTAL inserted: {grand}")
    conn.close()


if __name__ == "__main__":
    main()
