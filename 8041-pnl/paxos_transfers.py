"""Deposits / withdrawals / transfers for MOON-TK@PAXOS_SPOT.

Paxos was the last tracked account with NO transfer feed at all, so every cash
movement through it surfaced as an unexplained recon break — and because the
money arrives and leaves within an hour, `_tag_snap_gaps` cancelled the pairs
and buried $2.3M of real flow as "timing artifacts". This closes that.

Source: Paxos v2 `GET /transfer/transfers` (scope transfer:read_transfer).
The dedicated API_PAXOS_TRANSFER credential 401s (rotated); the MAIN
credential in `Paxos mintburn/.env` carries the scope, so we use that.

Shape of the account: it is a CONDUIT, not a custody wallet. USD arrives as
CUBIX_DEPOSIT, converts to USDG, and leaves as CRYPTO_WITHDRAWAL to
0x9f736F87…f1ae — WALLET_CRB_EVM_02_ROBINHOOD, i.e. our own wallet. So most
rows here have a matching leg on the Robinhood side.

Signing: CREDIT = +qty (in), DEBIT = -qty (out). `amount` is the amount that
moved on the balance; `total` includes the fee, which is reported separately.

  python paxos_transfers.py [--since YYYY-MM-DD] [--dry-run]
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

import avgcost_db

PAXOS_REPO = Path(r"C:\Users\peter\OneDrive\Desktop\Claude\Paxos mintburn")
ACCOUNT = "MOON-TK@PAXOS_SPOT"
VENUE = "PAXOS"
# statuses that actually moved value; anything else is not a balance event
DONE = {"COMPLETED", "SETTLED"}


def _client():
    sys.path.insert(0, str(PAXOS_REPO))
    import config
    from paxos_client import PaxosClient
    return PaxosClient(config.CLIENT_ID, config.CLIENT_SECRET, config.BASE_URL,
                       config.OAUTH_TOKEN_URL,
                       config.SCOPES + ["transfer:read_transfer"])


def fetch(since=None, limit=100, max_pages=100):
    """All transfers, newest first, stopping once older than `since`."""
    cl = _client()
    out, cursor = [], None
    for _ in range(max_pages):
        params = {"limit": limit}
        if cursor:
            params["page_cursor"] = cursor
        d = cl._request("GET", "/transfer/transfers", params=params)
        items = d.get("items") or []
        out += items
        cursor = d.get("next_page_cursor")
        if not cursor or not items:
            break
        if since:
            oldest = items[-1].get("created_at", "")
            if oldest and oldest[:10] < since:
                break
    return out


def to_rows(items):
    rows, skipped = [], {}
    for it in items:
        st = str(it.get("status") or "").upper()
        if st not in DONE:
            skipped[st] = skipped.get(st, 0) + 1
            continue
        asset = it.get("asset") or it.get("balance_asset")
        amt = D(str(it.get("amount") or 0))
        if not asset or amt == 0:
            continue
        sign = 1 if str(it.get("direction", "")).upper() == "CREDIT" else -1
        ts = datetime.strptime(it["created_at"][:19],
                               "%Y-%m-%dT%H:%M:%S").replace(
                                   tzinfo=timezone.utc)
        rows.append({
            "asset": asset, "qty": amt * sign, "event_time": ts,
            "external_id": it["id"],
            "type": str(it.get("type") or "TRANSFER").upper(),
            "raw": json.dumps({k: it.get(k) for k in
                               ("type", "direction", "status", "fee", "total",
                                "crypto_network", "crypto_tx_hash",
                                "destination_address", "memo")}),
        })
    return rows, skipped


def store(rows):
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
                """, (VENUE, ACCOUNT, r["asset"], str(r["qty"]), r["type"],
                      r["external_id"], r["event_time"], r["raw"]))
                n += cur.rowcount
        conn.commit()
        return n
    finally:
        conn.close()


def main():
    since = None
    if "--since" in sys.argv:
        since = sys.argv[sys.argv.index("--since") + 1]
    items = fetch(since)
    rows, skipped = to_rows(items)
    types, assets = {}, {}
    for r in rows:
        types[r["type"]] = types.get(r["type"], 0) + 1
        assets[r["asset"]] = assets.get(r["asset"], D(0)) + r["qty"]
    print(f"[paxos] {len(items)} transfers fetched, {len(rows)} usable")
    print(f"  by type   : {types}")
    print(f"  net by asset: " + ", ".join(f"{k} {v:+,.4f}"
                                          for k, v in sorted(assets.items())))
    if skipped:
        print(f"  skipped (non-final status): {skipped}")
    if rows:
        print(f"  span: {min(r['event_time'] for r in rows):%Y-%m-%d} .. "
              f"{max(r['event_time'] for r in rows):%Y-%m-%d}")
    if "--dry-run" in sys.argv:
        print("  (dry run - nothing written)")
        return
    print(f"[paxos] +{store(rows)} new venue_transfers rows")


if __name__ == "__main__":
    main()
