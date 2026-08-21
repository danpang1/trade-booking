"""Does the Dinari treasury wallet net to zero?

The wallet is a CONDUIT: SPCX is minted into it from Dinari, wrapped to
SPCX.DW, and bridged to Hyperliquid; redemptions come back the other way.
It should never hold inventory, so two things must both be true:

  1. CHAIN IDENTITY   every SPCX-equivalent token that entered has left.
     SPCX and SPCX.DW are the same economic asset (DW is the wrapper), so
     the check sums them together. Wraps cancel by construction.

  2. BOOK vs CHAIN    net booked (LONG - SHORT) must equal net bridged to
     Hyperliquid (out - in). A gap here is a trade that happened on-chain
     and was never booked, or vice versa.

Read-only.  python dinari_zero_check.py
"""
from __future__ import annotations

import json
import re
import urllib.request
from collections import defaultdict
from decimal import Decimal as D
from pathlib import Path

import dinari_swap_recon as dsr

REPO = Path(__file__).resolve().parent
ADDR = "0xb7c6a246c658814c5a879fbec61055ec9896fd3c"
HL = "0x8dc440b31a89"           # our Hyperliquid account (mint dest / burn src)
TOPIC = ("0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a"
         "4df523b3ef")
# SPCX and SPCX.DW are the same asset in different wrappers
SPCX_EQ = {"SPCX", "SPCX.DW"}


def flows():
    key = re.search(r"GOLDRUSH_API_KEY\s*[:=]\s*(\S+)",
                    (REPO / ".env").read_text(encoding="utf-8",
                                              errors="replace")
                    ).group(1).strip("\"'")
    tok = {a.lower(): (s, int(dc)) for a, (s, dc) in json.loads(
        (REPO / "dinari_token_map.json").read_text(encoding="utf-8")).items()}
    txs, url = [], (f"https://api.covalenthq.com/v1/hyperevm-mainnet/address/"
                    f"{ADDR}/transactions_v3/page/0/")
    hdr = {"User-Agent": "tokka-mo", "Authorization": f"Bearer {key}"}
    for _ in range(30):
        d = json.loads(urllib.request.urlopen(
            urllib.request.Request(url, headers=hdr), timeout=60
        ).read())["data"]
        txs += d.get("items") or []
        nxt = (d.get("links") or {}).get("next")
        if not nxt:
            break
        url = nxt
    legs = []
    for tx in txs:
        for lg in tx.get("log_events") or []:
            tp = lg.get("raw_log_topics") or []
            if not tp or tp[0] != TOPIC or len(tp) < 3:
                continue
            ca = str(lg.get("sender_address") or "").lower()
            if ca not in tok:
                continue
            sym, dec = tok[ca]
            frm = ("0x" + tp[1][-40:]).lower()
            to = ("0x" + tp[2][-40:]).lower()
            amt = D(int(lg.get("raw_log_data") or "0x0", 16)) / D(10) ** dec
            if to == ADDR:
                legs.append((tx["block_signed_at"][:19], sym, amt, frm, "IN"))
            if frm == ADDR:
                legs.append((tx["block_signed_at"][:19], sym, -amt, to, "OUT"))
    return legs


def main():
    legs = flows()
    # --- 1. chain identity: does the wallet net to zero? ---
    by_asset = defaultdict(D)
    for _, sym, amt, _, _ in legs:
        by_asset[sym] += amt
    spcx_eq = sum(v for k, v in by_asset.items() if k in SPCX_EQ)
    print("=== 1. WALLET RESIDUAL (all flows, wraps self-cancel) ===")
    for k, v in sorted(by_asset.items()):
        tag = "  <- SPCX-equivalent" if k in SPCX_EQ else ""
        print(f"   {k:8} {v:>18,.6f}{tag}")
    print(f"\n   SPCX + SPCX.DW combined : {spcx_eq:>14,.6f}")

    # --- 2. book vs chain, on the Hyperliquid leg ---
    to_hl = sum(-a for _, s, a, o, d_ in legs
                if s in SPCX_EQ and d_ == "OUT" and o.startswith(HL[:12]))
    from_hl = sum(a for _, s, a, o, d_ in legs
                  if s in SPCX_EQ and d_ == "IN" and o.startswith(HL[:12]))
    elsewhere = sum(-a for _, s, a, o, d_ in legs
                    if s in SPCX_EQ and d_ == "OUT"
                    and not o.startswith(HL[:12]) and int(o, 16) != 0)
    minted = sum(a for _, s, a, o, d_ in legs
                 if s in SPCX_EQ and d_ == "IN" and int(o, 16) == 0)
    books = dsr.prod_bookings()
    lng = sum(b["qty"] for b in books if str(b["dir"]).upper() == "LONG")
    sht = sum(b["qty"] for b in books if str(b["dir"]).upper() != "LONG")
    print("\n=== 2. BOOK vs CHAIN (Hyperliquid leg) ===")
    print(f"   chain: sent TO Hyperliquid    {to_hl:>14,.4f}")
    print(f"   chain: received FROM HL       {from_hl:>14,.4f}")
    print(f"   chain: NET delivered          {to_hl - from_hl:>14,.4f}")
    print(f"   books: LONG  ({sum(1 for b in books if str(b['dir']).upper()=='LONG'):>2} trades) "
          f"{lng:>14,.4f}")
    print(f"   books: SHORT ({sum(1 for b in books if str(b['dir']).upper()!='LONG'):>2} trades) "
          f"{sht:>14,.4f}")
    print(f"   books: NET                    {lng - sht:>14,.4f}")
    print(f"\n   BOOK - CHAIN gap              {(lng - sht) - (to_hl - from_hl):>14,.4f}")
    print("\n=== 3. where the SPCX went ===")
    print(f"   minted in from Dinari (0x0)   {minted:>14,.4f}")
    print(f"   sent to Hyperliquid           {to_hl:>14,.4f}")
    print(f"   returned from Hyperliquid     {from_hl:>14,.4f}")
    print(f"   sent to OTHER addresses       {elsewhere:>14,.4f}")
    print(f"   residual in wallet            {spcx_eq:>14,.6f}")


if __name__ == "__main__":
    main()
