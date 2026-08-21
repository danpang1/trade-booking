"""Book Paxos stablecoin conversions (swap-GUI export) into venue_transfers.

The /conversion API is not exposed to our credential (404), so the source of
truth is the swap GUI's export (paxos_conversions_swapgui.tsv, provided by
Peter 2026-08-03, profile 5f429307 = MOON-TK). Each conversion becomes TWO
rows: -source asset and +destination asset, type CONVERSION, keyed
conv:{id}:src / conv:{id}:dst — re-running is a no-op.

Destination amount is recorded = source amount (the export carries only one
figure); actual credits differ by sub-cent fees (e.g. 200,000 USD ->
199,999.996052 USDG), which is dust the recon absorbs.

  python paxos_conversions_import.py [--dry-run]
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

import avgcost_db

REPO = Path(__file__).resolve().parent
ACCOUNT = "MOON-TK@PAXOS_SPOT"
VENUE = "PAXOS"


def load():
    rows = []
    lines = (REPO / "paxos_conversions_swapgui.tsv").read_text(
        encoding="utf-8").splitlines()
    for ln in lines[1:]:
        if not ln.strip():
            continue
        cid, ts, src, dst, amt = ln.split("\t")
        t = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
        raw = json.dumps({"conversion_id": cid, "source": src,
                          "dest": dst, "amount": amt,
                          "origin": "swapgui export 2026-08-03"})
        for leg, asset, qty in (("src", src, -D(amt)), ("dst", dst, D(amt))):
            rows.append((VENUE, ACCOUNT, asset, str(qty), "CONVERSION",
                         f"conv:{cid}:{leg}", t, raw))
    return rows


def main():
    rows = load()
    n_conv = len(rows) // 2
    by = {}
    for r in rows:
        by[r[2]] = by.get(r[2], D(0)) + D(r[3])
    print(f"[conv] {n_conv} conversions -> {len(rows)} legs")
    print("  net by asset: " + ", ".join(
        f"{k} {v:+,.2f}" for k, v in sorted(by.items())))
    if "--dry-run" in sys.argv:
        print("  (dry run)")
        return
    from psycopg2.extras import execute_values
    conn = avgcost_db.connect()
    try:
        with conn.cursor() as cur:
            execute_values(cur, """
                INSERT INTO venue_transfers
                    (venue, account, asset, qty, transfer_type,
                     external_id, event_time, raw)
                VALUES %s
                ON CONFLICT (venue, account, external_id, asset) DO NOTHING
            """, rows, page_size=500)
            new = cur.rowcount
        conn.commit()
        print(f"[conv] +{new} new venue_transfers rows")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
