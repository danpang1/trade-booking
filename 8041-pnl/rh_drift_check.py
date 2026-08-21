"""Robinhood-chain drift check: GoldRush transfers_v2 vs stored fills.

Answers "did skipped/missed txs cause position drift?" WITHOUT the Blockscout
full-history walk (two attempts exhausted ~196K PRO credits without
completing). GoldRush is the independent index here — exactly the
cross-check role it already plays for balances.

Method, per token contract the wallet has traded:
  chain_net  = sum of the wallet's net per-tx deltas (GoldRush transfers_v2),
               capped at the DB ingest watermark
  engine_net = sum of stored signed fill qtys (trades_spot_avgcost)
  funding    = chain deltas from txs with NO stored fill AND no USDG leg
               (one-way inventory transfers — the RH funding model)
  residual   = chain_net - engine_net - funding  ->  missed fills, exactly

Txs absent from the DB but carrying a USDG leg are flagged MISSED-FILL with
their net qty (the 143 multi-base-token skips land here).

Usage: python rh_drift_check.py [--workers 4]
"""
import argparse
import json
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

import avgcost_db

REPO = Path(__file__).resolve().parent
RH_WALLET = "0x9f736f87e6293ac1bd9142e257dbfac8b7acf1ae"
USDG = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"
CHAIN = "robinhood-mainnet"
GR_TOKEN_MAP_P = REPO / "goldrush_token_map.json"


def env(key):
    for line in (REPO / ".env").read_text(encoding="utf-8",
                                          errors="replace").splitlines():
        if line.strip().startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return None


GR_KEY = env("GOLDRUSH_API_KEY")


def gr_get(url):
    for attempt in range(10):
        try:
            r = urllib.request.urlopen(urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60)
            d = json.loads(r.read())
            if not d.get("error"):
                return d.get("data") or {}
        except Exception:
            if attempt == 9:
                raise
        time.sleep(min(20, 2 * (attempt + 1)))
    raise RuntimeError("goldrush kept erroring")


def token_transfers(contract):
    """[(tx_hash, ts, net_delta_raw)] for the wallet on one contract, all
    pages. transfers_v2 items are tx-shaped with a transfers[] list."""
    out, page = [], 0
    while True:
        d = gr_get(f"https://api.covalenthq.com/v1/{CHAIN}/address/{RH_WALLET}"
                   f"/transfers_v2/?contract-address={contract}"
                   f"&page-size=1000&page-number={page}&key={GR_KEY}")
        items = d.get("items") or []
        for it in items:
            ts = it.get("block_signed_at")
            net = 0
            for tr in (it.get("transfers") or []):
                delta = int(tr.get("delta") or 0)
                net += delta if tr.get("transfer_type") == "IN" else -delta
            out.append((it.get("tx_hash", "").lower(), ts, net))
        pg = (d.get("pagination") or {})
        if not pg.get("has_more"):
            return out
        page += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    tok_map = {}
    if GR_TOKEN_MAP_P.exists():
        tok_map = json.loads(GR_TOKEN_MAP_P.read_text(
            encoding="utf-8")).get(CHAIN, {})
    sym_of = {c.lower(): v["symbol"] for c, v in tok_map.items()}
    dec_of = {c.lower(): int(v.get("decimals") or 18)
              for c, v in tok_map.items()}

    conn = avgcost_db.connect()
    cur = conn.cursor()
    cur.execute("""SELECT external_trade_id, base_asset,
                          CASE WHEN direction='LONG' THEN base_amount
                               ELSE -base_amount END,
                          trade_date
                   FROM trades_spot_avgcost
                   WHERE instrument LIKE '%%@ROBINHOOD'""")
    fills_by_tx = defaultdict(lambda: defaultdict(D))
    engine_net = defaultdict(D)
    watermark = None
    for ext, sym, sq, td in cur.fetchall():
        tx = ext.split(":")[0].lower()
        fills_by_tx[tx][sym.upper()] += D(sq)
        engine_net[sym.upper()] += D(sq)
        watermark = td if watermark is None or td > watermark else watermark
    conn.close()
    wm_iso = watermark.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"stored fills: {sum(len(v) for v in fills_by_tx.values())} legs "
          f"across {len(fills_by_tx)} txs; watermark {wm_iso}")

    # contracts to sweep = every traded ticker in the map + USDG for the
    # fill/funding distinction
    want = {c for c, s in sym_of.items() if s.upper() in engine_net}
    missing = set(engine_net) - {s.upper() for s in sym_of.values()}
    if missing:
        print(f"WARNING: no contract mapping for {sorted(missing)} — "
              "excluded from sweep")

    def cap_ok(ts):
        if not ts:
            return False
        t = datetime.strptime(ts.split(".")[0].rstrip("Z"),
                              "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        return t <= watermark

    usdg_txs = {tx for tx, ts, net in token_transfers(USDG) if net != 0}
    print(f"USDG stream: {len(usdg_txs)} txs with a USDG leg")

    def sweep(contract):
        sym = sym_of[contract].upper()
        dec = dec_of.get(contract, 18)
        rows = token_transfers(contract)
        chain_net = funding = missed = D(0)
        missed_txs = []
        for tx, ts, raw in rows:
            if not cap_ok(ts) or raw == 0:
                continue
            qty = D(raw) / D(10) ** dec
            chain_net += qty
            if tx in fills_by_tx:
                continue                      # matched (qty checked via residual)
            if tx in usdg_txs:
                missed += qty                 # fill-shaped tx we never stored
                missed_txs.append(tx)
            else:
                funding += qty                # one-way inventory transfer
        return (sym, chain_net, funding, missed, missed_txs, len(rows))

    results = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for res in ex.map(sweep, sorted(want)):
            results.append(res)
            print(f"  swept {res[0]:6} ({res[5]} txs)")

    print(f"\n{'ticker':7} {'chain net':>15} {'engine net':>15} "
          f"{'funding':>14} {'missed-fill':>13} {'residual':>12}  verdict")
    bad = 0
    for sym, chain_net, funding, missed, missed_txs, _n in sorted(results):
        resid = chain_net - engine_net[sym] - funding - missed
        ok = abs(resid) < D("0.0001") and missed == 0
        bad += 0 if ok else 1
        print(f"{sym:7} {chain_net:>15.4f} {engine_net[sym]:>15.4f} "
              f"{funding:>14.4f} {missed:>13.4f} {resid:>12.4f}  "
              f"{'OK' if ok else 'CHECK'}")
        for tx in missed_txs[:5]:
            print(f"        missed-fill tx: {tx}")
        if len(missed_txs) > 5:
            print(f"        ... +{len(missed_txs) - 5} more")
    print(f"\n{len(results)} tickers swept, {bad} with drift/missed fills")


if __name__ == "__main__":
    main()
