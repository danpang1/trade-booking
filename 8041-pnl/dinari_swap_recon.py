"""Reconcile Dinari primary-market SWAP CYCLES on-chain vs bookings in PROD.

The Dinari treasury wallet (0xb7c6…fd3c, HyperEVM) is a CONDUIT, not a custody
account. Every purchase is a 5-step cycle that completes in ~4 minutes:

    1. USDC in            funding arrives from treasury
    2. USDC out           payment to Dinari
    3. SPCX in  x N       delivery, minted in many small lots
    4. wrap               SPCX -> SPCX.DW, equal and opposite, nets to zero
    5. SPCX.DW out        bridged to Hyperliquid, arrives as SPCXD

Recording these legs as custody transfers is a category error — it produced
+449,843 USDC of phantom deposits and a NEGATIVE SPCX balance on 2026-08-03.
The economically meaningful object is the CYCLE, and each cycle should
correspond to exactly one booked trade in PROD `trades_spot`
(base_asset SPCX, counterparty DINARI, CENTRAL RISK BOOK).

The join key is the step-5 bridge-out QUANTITY, which matches the booked
base_amount exactly (verified to 4dp on 5 of 6 sampled cycles).

Read-only. Reports, changes nothing.

  python dinari_swap_recon.py [--tol 0.01]
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from decimal import Decimal as D
from pathlib import Path

REPO = Path(__file__).resolve().parent
ADDR = "0xb7c6a246c658814c5a879fbec61055ec9896fd3c"
CHAIN = "hyperevm-mainnet"
TOPIC = ("0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a"
         "4df523b3ef")


def _env(key, path=None):
    txt = (path or (REPO / ".env")).read_text(encoding="utf-8",
                                              errors="replace")
    m = re.search(rf"{key}\s*[:=]\s*(\S+)", txt)
    return m.group(1).strip("\"'") if m else None


def chain_cycles():
    """On-chain flows -> [{'qty','when','tx'}] one entry per bridge-out."""
    key = _env("GOLDRUSH_API_KEY")
    tok = {a.lower(): (s, int(d)) for a, (s, d) in json.loads(
        (REPO / "dinari_token_map.json").read_text(encoding="utf-8")).items()}
    # PAGINATION: the cursor is `next`, NOT `prev`. Page 0 is the OLDEST
    # page and `next` walks forward in time. Breaking on `prev` (as the other
    # GoldRush walkers in this repo do) stops after the first 100 txs — which
    # silently truncated this wallet's history at 2026-06-18 and made every
    # later booking look unmatched.
    txs = []
    url = (f"https://api.covalenthq.com/v1/{CHAIN}/address/{ADDR}"
           f"/transactions_v3/page/0/")
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
    print(f"  (chain: {len(txs)} txs pulled)")
    bridges, usdc_out, wraps = [], [], []
    for tx in txs:
        ins, outs = {}, {}
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
                ins[sym] = ins.get(sym, D(0)) + amt
            if frm == ADDR:
                outs[sym] = outs.get(sym, D(0)) + amt
        when, h = tx["block_signed_at"], tx["tx_hash"]
        # step 5: SPCX.DW out and nothing in => the bridge to Hyperliquid
        if outs.get("SPCX.DW") and not ins:
            bridges.append({"qty": outs["SPCX.DW"], "when": when, "tx": h})
        # step 2: USDC out and nothing in => payment to Dinari
        if outs.get("USDC") and not ins:
            usdc_out.append({"qty": outs["USDC"], "when": when, "tx": h})
        # step 4: the wrap, equal and opposite
        if ins.get("SPCX.DW") and outs.get("SPCX"):
            wraps.append({"qty": outs["SPCX"], "when": when, "tx": h})
    return (sorted(bridges, key=lambda x: x["when"]),
            sorted(usdc_out, key=lambda x: x["when"]),
            sorted(wraps, key=lambda x: x["when"]))


def _prod_mo_creds():
    """Parse the `#PROD MO DB RO` block from nxgenmo/.env.

    Deliberately duplicated from pnl_8041_daily rather than imported:
    THAT MODULE HAS NO `if __name__ == "__main__"` GUARD, so importing it
    executes the whole daily pipeline — ingest, PnL, recon. Doing so from
    here kicked off an unplanned venue ingest mid-rebuild (2026-08-03).
    Never `import pnl_8041_daily` from a helper.
    """
    envp = REPO.parent.parent / "nxgenmo" / ".env"
    creds, in_block = {}, False
    for ln in envp.read_text(encoding="utf-8", errors="replace").splitlines():
        s, st = ln.rstrip(), ln.strip()
        if st.startswith("#") and "PROD MO DB RO" in st.upper():
            in_block = True
            continue
        if not in_block:
            continue
        if st.startswith("#"):
            break
        if not st:
            continue
        # keys in this block use ':' OR '=' — take whichever comes first
        idxs = [i for i in (s.find(":"), s.find("=")) if i >= 0]
        if not idxs:
            continue
        i = min(idxs)
        creds[s[:i].strip().upper()] = s[i + 1:].strip().strip('"').strip("'")
    return creds


def prod_bookings():
    """Live Dinari SPCX bookings from PROD MO DB (source of truth)."""
    import psycopg2
    c = _prod_mo_creds()
    conn = psycopg2.connect(
        host=c["MO_DB_HOST"], port=int(c.get("MO_DB_PORT", "5432")),
        dbname=c["MO_DB_DATABASE"], user=c["MO_DB_USERNAME"],
        password=c["MO_DB_PASSWORD"], connect_timeout=20)
    try:
        cur = conn.cursor()
        cur.execute("SET TIMEZONE = 'UTC'")
        cur.execute("""
            SELECT deal_ref, base_amount, price, trade_date, direction, status
            FROM trades_spot
            WHERE base_asset = 'SPCX' AND counterparty = 'DINARI'
              AND effective_end IS NULL
              AND status <> 'CANCELLED'
              AND portfolio_name LIKE '%%CENTRAL RISK BOOK%%'
            ORDER BY trade_date, deal_ref
        """)
        return [{"deal_ref": r[0], "qty": D(str(r[1])), "px": D(str(r[2])),
                 "when": r[3], "dir": r[4], "status": r[5]}
                for r in cur.fetchall()]
    finally:
        conn.close()


def main():
    tol = D(sys.argv[sys.argv.index("--tol") + 1]) if "--tol" in sys.argv \
        else D("0.01")
    bridges, usdc_out, wraps = chain_cycles()
    books = prod_bookings()
    print(f"on-chain: {len(bridges)} bridge-outs, {len(usdc_out)} USDC "
          f"payments, {len(wraps)} wraps")
    print(f"PROD    : {len(books)} booked Dinari SPCX trades\n")
    used = set()
    print(f"{'booked deal':14} {'qty':>13} {'px':>10} {'booked at':17} "
          f"{'chain qty':>13} {'chain at':17} match")
    unmatched_books = []
    for b in books:
        best, bi = None, None
        for i, c in enumerate(bridges):
            if i in used:
                continue
            if abs(c["qty"] - b["qty"]) <= tol:
                best, bi = c, i
                break
        if best:
            used.add(bi)
            print(f"{b['deal_ref']:14} {b['qty']:>13,.4f} {b['px']:>10,.4f} "
                  f"{str(b['when'])[:16]:17} {best['qty']:>13,.4f} "
                  f"{best['when'][:16]:17} OK")
        else:
            unmatched_books.append(b)
            print(f"{b['deal_ref']:14} {b['qty']:>13,.4f} {b['px']:>10,.4f} "
                  f"{str(b['when'])[:16]:17} {'-':>13} {'-':17} NO CHAIN LEG")
    orphans = [c for i, c in enumerate(bridges) if i not in used]
    print(f"\n=== UNBOOKED on-chain cycles: {len(orphans)} ===")
    for c in orphans:
        print(f"  {c['when'][:19]}  {c['qty']:>13,.4f} SPCX.DW  tx {c['tx'][:20]}")
    print(f"\n=== booked with no chain leg: {len(unmatched_books)} ===")
    for b in unmatched_books:
        print(f"  {b['deal_ref']}  {b['qty']:,.4f} @ {b['px']:,.4f} "
              f"{str(b['when'])[:19]}")
    tb = sum(b["qty"] for b in books)
    tc = sum(c["qty"] for c in bridges)
    print(f"\ntotal booked qty : {tb:,.4f} SPCX")
    print(f"total bridged qty: {tc:,.4f} SPCX.DW")
    print(f"difference       : {tb - tc:,.4f}")


if __name__ == "__main__":
    main()
