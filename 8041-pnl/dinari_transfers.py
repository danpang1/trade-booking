"""Dinari treasury (HyperEVM) transfers via GoldRush.

!! NOT SAFE TO RUN — DISABLED 2026-08-03. !!
Reconstructing transfers from raw Transfer log events records BOTH SIDES of
Dinari's primary-market swaps as if they were custody movements. When it ran
it produced +449,843 USDC of phantom deposits and a NEGATIVE SPCX balance,
against a live wallet holding ~0 USDC. The already-booked-as-fill guard below
never fires: Dinari fills carry MO deal-ref ids (MFX...), not tx hashes, so
the tx-hash comparison matches nothing.

Because Dinari's hourly balances are RECONSTRUCTED from this transfer stream,
bad rows corrupt the snapshots as well — and the recon identity cannot catch
it (snap delta = transfers is a tautology there). The only tell is the tip
drift printed by dinari_goldrush_snaps vs the live wallet.

Before re-enabling: classify swap txs (wallet both sends AND receives in one
tx => not a transfer) the way chain_transfers.py does, and verify the tip
drift stays at the documented ~0.99 USDC dust.


`chain_transfers.py` walked https://www.hyperscan.com (a Blockscout instance)
for this wallet. On 2026-08-03 that host stopped serving the Blockscout API
entirely — every /api/v2/* path 404s and the domain now returns a marketing
page — so the DINARI leg of chain_transfers is dead, not merely erroring.

GoldRush already serves this wallet's hourly BALANCES (dinari_goldrush_snaps),
and its transactions_v3 endpoint carries log_events on hyperevm-mainnet, so
the same Transfer-topic reconstruction used for the CRB custody wallets works
here. Same shape, same `{tx}:{SYM}` external_id convention as the old walk, so
rows dedup against anything hyperscan already recorded.

No history was lost in the switch: the wallet's newest on-chain tx at the time
of the outage was 2026-06-18, matching the last recorded transfer (06-19), and
the recon showed zero Dinari breaks across its whole history.

  python dinari_transfers.py [YYYY-MM-DD]
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

import avgcost_db

REPO = Path(__file__).resolve().parent
ACCOUNT = "TOKKA_TREASURY_EVM_01_DINARI"
VENUE = "DINARI"
EXCH = "HYPEREVM"
WALLET = "0xb7c6a246c658814c5a879fbec61055ec9896fd3c"
CHAIN = "hyperevm-mainnet"
TOKENS = REPO / "dinari_token_map.json"
TRANSFER_TOPIC = ("0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a"
                  "4df523b3ef")
INCEPTION = datetime(2026, 6, 12, tzinfo=timezone.utc)


def _key():
    env = (REPO / ".env").read_text(encoding="utf-8", errors="replace")
    return re.search(r"GOLDRUSH_API_KEY\s*[:=]\s*(\S+)",
                     env).group(1).strip("\"'")


def _gr(path):
    url = f"https://api.covalenthq.com/v1/{CHAIN}/{path}"
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


def sync(since=None):
    """Reconstruct transfers from tx log events. Returns (inserted, seen)."""
    since = since or INCEPTION
    tokens = {a.lower(): (s, int(dec)) for a, (s, dec) in
              json.loads(TOKENS.read_text(encoding="utf-8")).items()}
    addr = WALLET.lower()
    rows, stop = [], False
    for page in range(12):
        if stop:
            break
        d = _gr(f"address/{addr}/transactions_v3/page/{page}/")
        items = d.get("items") or []
        if not items:
            break
        for tx in items:
            ts = datetime.strptime(tx["block_signed_at"],
                                   "%Y-%m-%dT%H:%M:%SZ").replace(
                                       tzinfo=timezone.utc)
            if ts < since:
                stop = True
                continue
            for lg in (tx.get("log_events") or []):
                tp = lg.get("raw_log_topics") or []
                if not tp or tp[0] != TRANSFER_TOPIC or len(tp) < 3:
                    continue
                caddr = str(lg.get("sender_address") or "").lower()
                if caddr not in tokens:
                    continue                  # spam / unmapped token
                sym, dec = tokens[caddr]
                frm = ("0x" + tp[1][-40:]).lower()
                to = ("0x" + tp[2][-40:]).lower()
                sign = (1 if to == addr else 0) + (-1 if frm == addr else 0)
                if not sign:
                    continue
                amt = D(int(lg.get("raw_log_data") or "0x0", 16)) / D(10) ** dec
                if amt == 0:
                    continue
                rows.append({
                    "asset": sym, "qty": amt * sign, "event_time": ts,
                    "external_id": f"{tx['tx_hash'].lower()}:{sym}",
                    "type": "DEPOSIT" if sign > 0 else "WITHDRAWAL",
                    "raw": json.dumps({"tx": tx["tx_hash"], "chain": CHAIN,
                                       "src": "goldrush"})})
        if not (d.get("links") or {}).get("prev"):
            break
    # a tx already booked as a FILL is never also a transfer — Dinari's
    # primary-market buys are booked into the HL SPCXD leg, and recording
    # their token legs here would double-explain the position
    conn = avgcost_db.connect()
    n = 0
    try:
        txs = list({r["external_id"].split(":")[0] for r in rows})
        fill_txs = set()
        if txs:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT split_part(external_trade_id, ':', 1)
                    FROM trades_spot_avgcost
                    WHERE venue = %s
                      AND split_part(external_trade_id, ':', 1) = ANY(%s)
                """, (VENUE, txs))
                fill_txs = {r[0] for r in cur.fetchall()}
        keep = [r for r in rows
                if r["external_id"].split(":")[0] not in fill_txs]
        if len(keep) != len(rows):
            print(f"  ({len(rows) - len(keep)} legs dropped — tx already "
                  "booked as a fill)")
        with conn.cursor() as cur:
            for r in keep:
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
        return n, len(rows)
    finally:
        conn.close()


if __name__ == "__main__":
    since = (datetime.strptime(sys.argv[1], "%Y-%m-%d").replace(
        tzinfo=timezone.utc) if len(sys.argv) > 1 else INCEPTION)
    ins, seen = sync(since)
    print(f"[{ACCOUNT}] +{ins} transfer rows ({seen} legs seen since "
          f"{since:%Y-%m-%d})")
