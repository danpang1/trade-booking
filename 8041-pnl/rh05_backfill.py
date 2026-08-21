"""Backfill WALLET_CRB_EVM_05_ROBINHOOD (GME RFQ wallet) fills from the
chain walk (swap txs -> fills, source 'chain'), account-scoped legs."""
from datetime import datetime, timezone

import avgcost_db
import chain_transfers as ct

ACCT = "WALLET_CRB_EVM_05_ROBINHOOD"
START = datetime(2026, 7, 22, tzinfo=timezone.utc)

fills_by_tk = ct.chain_fills("ROBINHOOD_05", START)
conn = avgcost_db.connect()
total = 0
for tk, fills in sorted(fills_by_tk.items()):
    leg = {"venue": "ROBINHOOD", "account": ACCT,
           "instrument": f"{tk}/USDG@ROBINHOOD", "product": "SPOT",
           "quote_asset": "USDG", "counterparty": None}
    ins, fresh, refold = avgcost_db.ingest_leg(conn, leg, fills)
    conn.commit()
    total += ins
    print(f"[rh05] {tk}: {ins} inserted ({len(fills)} pulled, {fresh} fresh)"
          + (f", refold: {refold}" if refold else ""), flush=True)
print(f"RH05_BACKFILL_DONE total={total}")
conn.close()
