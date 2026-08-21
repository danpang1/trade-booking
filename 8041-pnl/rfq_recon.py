"""Recon ClickHouse production.rfq_fill vs chain truth (Blockscout-sourced
fills stored in trades_spot_avgcost) for the Robinhood-chain RFQ maker wallet.

Chain side  = stored @ROBINHOOD fills (ingested from Blockscout, id-deduped).
RFQ side    = rfq_fill rows for chain_id 4663 + our maker, summed per
              (tx, ticker, side) since batched txs carry multiple order_hashes.

Statuses: MATCHED / QTY_MISMATCH / MISSING_IN_RFQ (on chain, absent in CH)
          / PHANTOM (in CH, absent on chain — verified live vs Blockscout).

Usage: python rfq_recon.py --start 2026-07-13 [--end "2026-07-16 08:00:00"]
                           [--out rfq_recon.csv]
"""
import argparse
import csv
import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

import avgcost_db

# Blockscout PRO key from .env (optional) — lifts the anonymous rate cap.
BLOCKSCOUT_KEY = ""
for _l in (avgcost_db.REPO / ".env").read_text(
        encoding="utf-8", errors="replace").splitlines():
    if _l.strip().startswith("BLOCKSCOUT_API_KEY="):
        BLOCKSCOUT_KEY = _l.split("=", 1)[1].strip()

CH = ("https://jp-clickhouse-api.internal.tokkalabs.com:443/"
      "?user=prod_ro&password=scCtp%21Ez8%233h%23LK8")
MAKER = "0x9f736f87e6293ac1bd9142e257dbfac8b7acf1ae"
USDG = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"   # 6 dp quote token
CHAIN_ID = 4663

ap = argparse.ArgumentParser()
ap.add_argument("--start", required=True)
ap.add_argument("--end", default=None,
                help="default: newest stored @ROBINHOOD fill minus 15 min "
                     "(avoids false breaks at the chain-ingest tip)")
ap.add_argument("--out", default="rfq_recon.csv")
args = ap.parse_args()


def ch(sql):
    r = urllib.request.urlopen(urllib.request.Request(
        CH, data=sql.encode(), headers={"Content-Type": "text/plain"}),
        timeout=120)
    body = r.read().decode()
    return [ln.split("\t") for ln in body.splitlines() if ln]


tok = json.load(open("goldrush_token_map.json", encoding="utf-8"))
TOKENS = {a.lower(): (v["symbol"].upper(), int(v["decimals"]))
          for a, v in tok["robinhood-mainnet"].items()}

# ── chain side: stored Blockscout fills ────────────────────────────────
con = avgcost_db.connect()
cur = con.cursor()
cur.execute("SELECT max(trade_date) FROM trades_spot_avgcost "
            "WHERE instrument LIKE '%%@ROBINHOOD'")
db_max = cur.fetchone()[0]
end = args.end or (db_max - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
print(f"window: {args.start} .. {end} UTC  (stored fills through {db_max})")

cur.execute("""
    SELECT external_trade_id, direction, base_amount, price, trade_date
    FROM trades_spot_avgcost
    WHERE instrument LIKE '%%@ROBINHOOD'
      AND trade_date >= %s AND trade_date <= %s
""", (args.start, end))
chain = {}   # (tx, ticker) -> row
for ext, direction, qty, px, td in cur.fetchall():
    tx, ticker = ext.rsplit(":", 1)
    chain[(tx.lower(), ticker)] = {
        "side": direction, "qty": Decimal(qty), "px": Decimal(px), "t": td}
print(f"chain fills (stored): {len(chain)}")

# ── rfq side: ClickHouse, summed per (tx, ticker, side) ────────────────
rows = ch(f"""
    SELECT transaction_hash, venue, toString(ts_fill),
           lower(maker_token_address), lower(taker_token_address),
           maker_token_filled_amount, taker_token_filled_amount
    FROM production.rfq_fill
    WHERE chain_id={CHAIN_ID} AND lower(maker_address)='{MAKER}'
      AND ts_fill >= '{args.start}' AND ts_fill <= '{end}'
    FORMAT TabSeparated
""")
rfq = {}     # (tx, ticker) -> agg
skipped = 0
for tx, venue, ts, mtok, ttok, mamt, tamt in rows:
    if mtok == USDG:                       # we pay USDG, receive taker token
        side, base_tok = "BUY", ttok
        base_raw, usdg_raw = int(tamt or 0), int(mamt or 0)
    elif ttok == USDG:                     # we deliver token, receive USDG
        side, base_tok = "SELL", mtok
        base_raw, usdg_raw = int(mamt or 0), int(tamt or 0)
    else:
        skipped += 1
        continue
    sym_dec = TOKENS.get(base_tok)
    if sym_dec is None:
        sym_dec = (base_tok[:10], 18)
    ticker, dec = sym_dec
    k = (tx.lower(), ticker)
    a = rfq.setdefault(k, {"side": side, "venue": venue, "t": ts,
                           "base": 0, "usdg": 0, "dec": dec})
    if a["side"] != side:
        a["side"] = "MIXED"
    a["base"] += base_raw
    a["usdg"] += usdg_raw
print(f"rfq_fill rows: {len(rows)} -> {len(rfq)} tx-legs"
      + (f"  ({skipped} non-USDG rows skipped)" if skipped else ""))

# ── compare ────────────────────────────────────────────────────────────
out = []


def _when(k):
    c, r = chain.get(k), rfq.get(k)
    return str(c["t"])[:19] if c else r["t"][:19]


for k in sorted(set(chain) | set(rfq), key=_when):
    tx, ticker = k
    c, r = chain.get(k), rfq.get(k)
    if c and r:
        rqty = Decimal(r["base"]) / Decimal(10) ** r["dec"]
        rpx = ((Decimal(r["usdg"]) / Decimal(10) ** 6) / rqty
               if rqty else Decimal(0))
        diff = abs(c["qty"]) - rqty
        status = "MATCHED" if abs(diff) < Decimal("1e-9") else "QTY_MISMATCH"
        out.append([str(c["t"])[:19], ticker,
                    "LONG" if c["side"] in ("BUY", "LONG") else "SHORT",
                    f"{abs(c['qty']):.8f}", f"{c['px']:.4f}",
                    r["venue"], r["side"], f"{rqty:.8f}", f"{rpx:.4f}",
                    f"{diff:.10f}", status, tx])
    elif c:
        out.append([str(c["t"])[:19], ticker,
                    "LONG" if c["side"] in ("BUY", "LONG") else "SHORT",
                    f"{abs(c['qty']):.8f}", f"{c['px']:.4f}",
                    "", "", "", "", "", "MISSING_IN_RFQ", tx])
    else:
        rqty = Decimal(r["base"]) / Decimal(10) ** r["dec"]
        rpx = ((Decimal(r["usdg"]) / Decimal(10) ** 6) / rqty
               if rqty else Decimal(0))
        out.append([r["t"][:19], ticker, "", "", "",
                    r["venue"], r["side"], f"{rqty:.8f}", f"{rpx:.4f}",
                    "", "PHANTOM?", tx])

# ── missing rows: check rfq_fill again WITHOUT the maker filter ────────
# (a fill recorded under empty/other maker is an attribution bug, not a drop)
miss_txs = sorted({row[11] for row in out if row[10] == "MISSING_IN_RFQ"})
if miss_txs:
    inlist = ",".join("'" + t + "'" for t in miss_txs)
    found = {r[0] for r in ch(
        f"SELECT DISTINCT transaction_hash FROM production.rfq_fill "
        f"WHERE transaction_hash IN ({inlist}) FORMAT TabSeparated")}
    for row in out:
        if row[10] == "MISSING_IN_RFQ" and row[11] in found:
            row[10] = "MISATTRIBUTED_IN_RFQ"

# ── verify phantom candidates against Blockscout live ──────────────────


def tx_on_chain(tx):
    if BLOCKSCOUT_KEY:  # metered PRO gateway; instance ignores apikey
        url = (f"https://api.blockscout.com/4663/api/v2/transactions/{tx}"
               f"?apikey={BLOCKSCOUT_KEY}")
    else:
        url = f"https://robinhoodchain.blockscout.com/api/v2/transactions/{tx}"
    for attempt in range(6):
        try:
            r = urllib.request.urlopen(urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30)
            d = json.loads(r.read())
            return d.get("status")        # 'ok' / 'error'
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return "404"
        except urllib.error.URLError:
            pass
        time.sleep(2 * (attempt + 1))
    return "unknown"


phantom_txs = sorted({row[11] for row in out if row[10] == "PHANTOM?"})
verdicts = {}
for tx in phantom_txs:
    verdicts[tx] = tx_on_chain(tx)
    time.sleep(0.2)
for row in out:
    if row[10] == "PHANTOM?":
        v = verdicts[row[11]]
        row[10] = ("PHANTOM_404" if v == "404"
                   else "PHANTOM_REVERTED" if v == "error"
                   else "ONCHAIN_MISSING_IN_DB" if v == "ok"
                   else "PHANTOM_UNVERIFIED")

hdr = ["time_utc", "ticker", "chain_side", "chain_qty", "chain_px",
       "rfq_venue", "rfq_side", "rfq_qty", "rfq_px", "qty_diff",
       "status", "tx_hash"]
with open(args.out, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(hdr)
    w.writerows(out)

counts = defaultdict(int)
for row in out:
    counts[row[10]] += 1
print(f"\nwrote {args.out} ({len(out)} rows)")
for s, n in sorted(counts.items()):
    print(f"  {s:24s} {n}")

miss = [r for r in out if r[10] == "MISSING_IN_RFQ"]
if miss:
    print("\nMISSING_IN_RFQ windows (contiguous <=10 min apart):")
    groups, cur_g = [], [miss[0]]
    from datetime import datetime as dt
    for r in miss[1:]:
        prev = dt.strptime(cur_g[-1][0], "%Y-%m-%d %H:%M:%S")
        this = dt.strptime(r[0], "%Y-%m-%d %H:%M:%S")
        if (this - prev).total_seconds() <= 600:
            cur_g.append(r)
        else:
            groups.append(cur_g)
            cur_g = [r]
    groups.append(cur_g)
    for g in groups:
        print(f"  {g[0][0]} .. {g[-1][0]}  ({len(g)} fills)")
bad = [r for r in out if r[10].startswith(("PHANTOM", "QTY_MISMATCH",
                                           "ONCHAIN_MISSING"))]
if bad:
    print("\nnon-missing breaks:")
    for r in bad[:40]:
        print("  " + " | ".join(str(x) for x in
                                (r[0], r[1], r[5], r[6], r[7], r[10], r[11][:16])))
