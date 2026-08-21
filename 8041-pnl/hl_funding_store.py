"""Persist Hyperliquid funding payments to venue_transfers.

Funding was only ever fetched LIVE at recon time. That works today because
`userFunding` still returns full history — but `userFills` also looked fine
until its ~10k retention silently hid 1,338 HYPE fills. A live-only dependency
on a venue endpoint is a latent version of that same failure, so funding is now
recorded as it is seen.

Identity: the funding `hash` is all zeroes for every event, so it cannot be the
key. Funding is charged once per coin per hourly settlement, so
`fund:{epoch_ms}:{coin}` is unique and stable — re-running is a no-op.

Sign convention matches the venue: `usdc` is the CREDIT to the account, so a
negative value is funding PAID. Stored as-is; the recon adds it to cash.

Pool matters: main-dex funding settles in USDC, HIP-3 (`xyz:`) funding settles
in the xyz pool's USDC. They are separate balances on the board, so the asset
is written as `USDC` or `xyz:USDC` accordingly.

  python hl_funding_store.py [--days N] [--since YYYY-MM-DD] [--dry-run]
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import avgcost_db
import hl_flows

ACCOUNT = "TRADING_06@HYPERLIQUID_FUTURES"
VENUE = "HYPERLIQUID"


def fetch(start_ms, end_ms):
    rows = []
    for u in hl_flows._paged("userFunding", start_ms, end_ms):
        d = u.get("delta") or {}
        coin = str(d.get("coin") or "")
        usdc = D(str(d.get("usdc") or 0))
        if usdc == 0:
            continue
        t = int(u["time"])
        # HIP-3 perps settle against the xyz pool's USDC, not main USDC
        asset = "xyz:USDC" if coin.startswith("xyz:") else "USDC"
        rows.append({
            "asset": asset, "qty": usdc,
            "event_time": datetime.fromtimestamp(t / 1000, timezone.utc),
            "external_id": f"fund:{t}:{coin}",
            "raw": json.dumps({"coin": coin, "szi": d.get("szi"),
                               "fundingRate": d.get("fundingRate")}),
        })
    return rows


def store(rows):
    conn = avgcost_db.connect()
    n = 0
    try:
        from psycopg2.extras import execute_values
        tuples = [(VENUE, ACCOUNT, r["asset"], str(r["qty"]), "FUNDING",
                   r["external_id"], r["event_time"], r["raw"]) for r in rows]
        with conn.cursor() as cur:
            for i in range(0, len(tuples), 2000):
                execute_values(cur, """
                    INSERT INTO venue_transfers
                        (venue, account, asset, qty, transfer_type,
                         external_id, event_time, raw)
                    VALUES %s
                    ON CONFLICT (venue, account, external_id, asset)
                    DO NOTHING
                """, tuples[i:i + 2000], page_size=2000)
                n += cur.rowcount
        conn.commit()
        return n
    finally:
        conn.close()


def main():
    now = datetime.now(timezone.utc)
    if "--since" in sys.argv:
        t0 = datetime.strptime(sys.argv[sys.argv.index("--since") + 1],
                               "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        days = int(sys.argv[sys.argv.index("--days") + 1]) \
            if "--days" in sys.argv else 3
        t0 = now - timedelta(days=days)
    rows = fetch(int(t0.timestamp() * 1000), int(now.timestamp() * 1000))
    by_asset = {}
    for r in rows:
        by_asset[r["asset"]] = by_asset.get(r["asset"], D(0)) + r["qty"]
    print(f"[funding] {len(rows):,} events {t0:%Y-%m-%d} .. {now:%Y-%m-%d}")
    print("  net by pool: " + ", ".join(f"{k} {v:+,.4f}"
                                        for k, v in sorted(by_asset.items())))
    if "--dry-run" in sys.argv:
        print("  (dry run — nothing written)")
        return
    print(f"[funding] +{store(rows)} new venue_transfers rows")


if __name__ == "__main__":
    main()
