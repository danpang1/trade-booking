"""Ethereum-mainnet RFQ maker fills from ClickHouse production.rfq_fill.

Source switch 2026-07-29 (was: eth.blockscout token-transfer walk covering the
WETH/USDC pair only). The wallet (WALLET_ETH_RFQ_01, 0x391af4…6865) quotes
1inch RFQ across FIVE pairs: WETH<->USDC, WETH<->USDT, WBTC<->USDC/USDT,
cbBTC<->USDC — the chain walk silently missed everything but ETH/USDC.

Legs: {BASE}/{QUOTE}@ETHEREUM_RFQ, BASE in (ETH [folds WETH], WBTC, CBBTC),
QUOTE in (USDC, USDT). external_trade_id = '{tx}:{BASE}' — same convention as
the old Blockscout ingest so the store's unique key dedups the overlap.
Token metadata resolves once per address via eth.blockscout and caches to
eth_token_map.json.
"""
from __future__ import annotations

import json
import time
import urllib.request
from collections import defaultdict
from decimal import Decimal as D
from pathlib import Path

from robinhood_ch_source import _ch, _env

REPO = Path(__file__).resolve().parent
CACHE = REPO / "eth_token_map.json"

ETH_CHAIN_ID = 1
ETH_WALLET = "0x391af49b1793529f430c4b5918da6bb237306865"
STABLES = {"USDC", "USDT"}
BS_TOKEN_API = "https://eth.blockscout.com/api/v2/tokens/"


def _bs_token(addr):
    url = BS_TOKEN_API + addr
    key = _env("BLOCKSCOUT_API_KEY")
    if key:
        url = url.replace("https://eth.blockscout.com/",
                          "https://api.blockscout.com/1/") + "?apikey=" + key
    for attempt in range(6):
        try:
            r = urllib.request.urlopen(urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20)
            d = json.loads(r.read())
            return (str(d.get("symbol") or "?").upper(),
                    int(d.get("decimals") or 18))
        except Exception:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"eth token lookup failed for {addr}")


def token_map(addresses):
    cache = {}
    if CACHE.exists():
        cache = json.loads(CACHE.read_text(encoding="utf-8"))
    missing = [a for a in addresses if a not in cache]
    for a in missing:
        cache[a] = list(_bs_token(a))
        print(f"  (eth token map: {a[:10]}… -> {cache[a][0]})")
    if missing:
        CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return cache


def _norm_base(sym):
    return "ETH" if sym in ("WETH", "ETH") else sym


def ch_rfq_events(since_ms=None):
    """{(base, quote) -> [canonical fill dicts]} for the ETH RFQ wallet."""
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
        WHERE chain_id = {ETH_CHAIN_ID}
          AND lower(maker_address) = '{ETH_WALLET}'
          {cond}
        GROUP BY transaction_hash, ttok, mtok
        FORMAT TSV"""
    rows = []
    for line in _ch(sql).splitlines():
        tx, ttok, mtok, tamt, mamt, t_ms = line.split("\t")
        rows.append((tx.lower(), ttok, mtok, int(tamt), int(mamt), int(t_ms)))
    addrs = {a for r in rows for a in (r[1], r[2])}
    tmap = token_map(sorted(addrs))

    by_leg = defaultdict(list)
    skipped = 0
    for tx, ttok, mtok, tamt, mamt, t_ms in rows:
        if tamt == 0 or mamt == 0:
            skipped += 1
            continue
        tsym, tdec = tmap[ttok]
        msym, mdec = tmap[mtok]
        tq = D(tamt) / D(10) ** tdec
        mq = D(mamt) / D(10) ** mdec
        # maker sends maker_token, receives taker_token
        if msym in STABLES and tsym not in STABLES:      # BUY base
            base, quote = _norm_base(tsym), msym
            qty, cash, sign = tq, mq, D(1)
        elif tsym in STABLES and msym not in STABLES:    # SELL base
            base, quote = _norm_base(msym), tsym
            qty, cash, sign = mq, tq, D(-1)
        else:
            skipped += 1                                 # stable<->stable etc.
            continue
        by_leg[(base, quote)].append({
            "external_trade_id": tx + ":" + base,
            "trade_date_ms": t_ms,
            "signed_qty": qty * sign,
            "price": cash / qty,
            "fee_amount": D("0"),
            "fee_asset": quote,
            "base_asset": base,
            "source": "clickhouse",
        })
    if skipped:
        print(f"  (eth rfq: {skipped} zero/stable-pair rows skipped)")
    return by_leg


if __name__ == "__main__":
    ev = ch_rfq_events()
    print("legs:", {f"{b}/{q}": len(v) for (b, q), v in sorted(ev.items())})
