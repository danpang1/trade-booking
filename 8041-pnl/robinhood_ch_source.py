"""Robinhood-chain RFQ maker fills from ClickHouse production.rfq_fill.

Source switch 2026-07-28 (was: Blockscout token-transfer reconstruction —
robinhood_rfq_events in pnl_8041_daily, kept as fallback). rfq_fill gained
maker_address + venue (zerox / arcus) ~2026-07-06 and now carries the whole
CRB_EVM_02 flow. Known caveats (accepted): rare collector-outage gaps and
phantom fills (reverted txs) — both surface as recon breaks, not silent loss.

Maker point of view: we SEND maker_token, RECEIVE taker_token.
    taker_token = equity -> BUY  (qty +, USDG out = maker side)
    maker_token = equity -> SELL (qty -, USDG in  = taker side)
external_trade_id = '{tx_hash}:{TICKER}' — same convention as the Blockscout
ingest, so the store's unique key dedups the overlap between the two sources.

Token metadata (address -> symbol/decimals) resolves via Blockscout
/api/v2/tokens/{addr} once per address and caches to rh_token_map.json.
USDG = 0x5fc5...d168 (6 decimals); equity tokens are 18.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from decimal import Decimal as D
from pathlib import Path

REPO = Path(__file__).resolve().parent
CACHE = REPO / "rh_token_map.json"

CH_URL = ("https://jp-clickhouse-api.internal.tokkalabs.com:443/"
          "?user=prod_ro&password=scCtp%21Ez8%233h%23LK8")
RH_CHAIN_ID = 4663
RH_WALLET = "0x9f736f87e6293ac1bd9142e257dbfac8b7acf1ae"
USDG_ADDR = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"
BS_TOKEN_API = "https://robinhoodchain.blockscout.com/api/v2/tokens/"


def _env(key):
    for line in (REPO / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return None


def _ch(sql):
    req = urllib.request.Request(CH_URL, data=sql.encode())
    return urllib.request.urlopen(req, timeout=60).read().decode()


def _bs_token(addr):
    """Blockscout token metadata (symbol, decimals) for one address."""
    url = BS_TOKEN_API + addr
    key = _env("BLOCKSCOUT_API_KEY")
    if key:
        url = url.replace("https://robinhoodchain.blockscout.com/",
                          "https://api.blockscout.com/4663/") + "?apikey=" + key
    for attempt in range(6):
        try:
            r = urllib.request.urlopen(urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20)
            d = json.loads(r.read())
            sym = str(d.get("symbol") or "?").upper()
            dec = int(d.get("decimals") or 18)
            return sym, dec
        except Exception:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Blockscout token lookup failed for {addr}")


def token_map(addresses):
    """{address: [symbol, decimals]}, cached across runs."""
    cache = {}
    if CACHE.exists():
        cache = json.loads(CACHE.read_text(encoding="utf-8"))
    missing = [a for a in addresses if a not in cache]
    for a in missing:
        cache[a] = list(_bs_token(a))
        print(f"  (rh token map: {a[:10]}… -> {cache[a][0]})")
    if missing:
        CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return cache


def ch_rfq_events(since_ms=None):
    """{ticker -> [canonical fill dicts]} from rfq_fill (maker = CRB_EVM_02).

    Aggregates per (tx, taker_token, maker_token) — defensive against split
    rows — and derives BUY/SELL from which side the equity token is on."""
    cond = ""
    if since_ms is not None:
        cond = f"AND ts_fill >= fromUnixTimestamp64Milli({since_ms})"
    sql = f"""
        SELECT transaction_hash,
               lower(taker_token_address)  AS ttok,
               lower(maker_token_address)  AS mtok,
               sum(toUInt256OrZero(coalesce(nullIf(taker_token_filled_amount, ''),
                                            taker_token_quoted_amount))) AS tamt,
               sum(toUInt256OrZero(coalesce(nullIf(maker_token_filled_amount, ''),
                                            maker_token_quoted_amount))) AS mamt,
               min(toUnixTimestamp64Milli(ts_fill)) AS t_ms
        FROM production.rfq_fill
        WHERE chain_id = {RH_CHAIN_ID}
          AND lower(maker_address) = '{RH_WALLET}'
          {cond}
        GROUP BY transaction_hash, ttok, mtok
        FORMAT TSV"""
    rows = []
    for line in _ch(sql).splitlines():
        tx, ttok, mtok, tamt, mamt, t_ms = line.split("\t")
        rows.append((tx.lower(), ttok, mtok, int(tamt), int(mamt), int(t_ms)))
    addrs = {a for r in rows for a in (r[1], r[2])}
    tmap = token_map(sorted(addrs))

    by_ticker = defaultdict(list)
    skipped = 0
    for tx, ttok, mtok, tamt, mamt, t_ms in rows:
        if tamt == 0 or mamt == 0:
            skipped += 1
            continue
        if ttok == USDG_ADDR and mtok != USDG_ADDR:      # SELL equity
            base_addr, base_amt, usdg_amt, sign = mtok, mamt, tamt, D(-1)
        elif mtok == USDG_ADDR and ttok != USDG_ADDR:    # BUY equity
            base_addr, base_amt, usdg_amt, sign = ttok, tamt, mamt, D(1)
        else:
            skipped += 1                                 # non-USDG pair
            continue
        sym, dec = tmap[base_addr]
        ticker = "WETH" if sym in ("WETH", "ETH") else sym
        qty = D(base_amt) / D(10) ** dec
        px = (D(usdg_amt) / D(10) ** 6) / qty
        by_ticker[ticker].append({
            "external_trade_id": tx + ":" + ticker,
            "trade_date_ms": t_ms,
            "signed_qty": qty * sign,
            "price": px,
            "fee_amount": D("0"),
            "fee_asset": "USDG",
            "base_asset": ticker,
            "source": "clickhouse",
        })
    if skipped:
        print(f"  (rh clickhouse: {skipped} zero-amount/non-USDG rows skipped)")
    return by_ticker


if __name__ == "__main__":
    import sys
    since = int(sys.argv[1]) if len(sys.argv) > 1 else None
    ev = ch_rfq_events(since)
    n = sum(len(v) for v in ev.values())
    print(f"tickers: {len(ev)}  fills: {n}")
    for t, fl in sorted(ev.items(), key=lambda x: -len(x[1]))[:8]:
        print(f"  {t}: {len(fl)}")
