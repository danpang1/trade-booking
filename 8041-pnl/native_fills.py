"""Native Core `userFills` -> canonical fill dicts for the avg-cost engine.

This is the FORWARD path. Native prunes fills outside the most recent ~10k
blocks (block time = 50 ms => the window is only ~8.3 MINUTES) and stores no
cost basis, so there is no history to backfill. The collector
(stream_native_fills.py) MUST poll every couple of minutes to accumulate fills
into trades_spot_avgcost — an hourly cadence (like the balance/position
streamers) would miss ~52 of every 60 minutes of fills. From the moment it runs
continuously, avg-cost / realized PnL are exact; before that, nothing.

Fill shape (validated live, wallet TRADING_01@NATIVECORE):
  fee, fee_asset_id, fee_mode, height, market_id, price(decimal str),
  quantity(decimal str, unsigned), maker/taker _owner/_oid/_cloid, role,
  tx_hash, tx_index.
There is NO side field on a fill. Direction is recovered from the resting
order via `orderStatus(oid, market_id)` (our wallet is always the maker):
  order.side == 'bid' -> BUY (+qty),  'ask' -> SELL (-qty).
There is also no fill timestamp; it is derived from `height` at 50 ms/block
anchored on the live height + fetch wall-clock.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
from native_common import (post_info, WALLET, live_height, markets_map,  # noqa: E402
                           INSTR_VENUE, D)

WINDOW = 9000          # blocks per userFills call (< 10k range + retention cap)
PAGE_LIMIT = 500       # server max_limit
BLOCK_MS = 50          # measured Native block time (50 ms/block)
_W = WALLET.lower()


def fetch_window_fills(from_height: int, to_height: int) -> list[dict]:
    """Raw userFills across [from_height, to_height], deduped by (tx_hash, tx_index)."""
    out, seen = [], set()
    fr = from_height
    while fr <= to_height:
        to = min(fr + WINDOW, to_height)
        resp = post_info({"type": "userFills", "user": WALLET,
                          "from_height": str(fr), "to_height": str(to),
                          "limit": str(PAGE_LIMIT)})
        for fl in (resp.get("fills") or []):
            key = (fl.get("tx_hash"), fl.get("tx_index"))
            if key in seen:
                continue
            seen.add(key)
            out.append(fl)
        fr = to + 1
    return out


def order_side_sign(fill: dict, cache: dict):
    """+1 (buy) / -1 (sell) for a fill, via the maker order's side. None if the
    order can no longer be resolved (pruned) — caller must skip such a fill
    rather than risk a wrong-direction fold."""
    we_maker = str(fill.get("maker_owner", "")).lower() == _W
    oid = fill["maker_oid"] if we_maker else fill["taker_oid"]
    mid = fill["market_id"]
    ck = (oid, mid)
    if ck not in cache:
        try:
            o = post_info({"type": "orderStatus", "user": WALLET,
                           "oid": str(oid), "market_id": str(mid)})
        except Exception:
            cache[ck] = None
            return None
        side = (o.get("order") or {}).get("side") if o.get("found") else None
        cache[ck] = (D(1) if side == "bid" else D(-1) if side == "ask" else None)
    return cache[ck]


def normalize_fill(raw: dict, markets: dict, live_h: int, fetch_ms: int,
                   side_cache: dict) -> dict | None:
    """One raw fill -> canonical dict for the avg-cost fold, or None if its
    market is unknown or its side cannot be resolved."""
    mid = int(raw["market_id"])
    meta = markets.get(mid)
    if not meta:
        return None
    sign = order_side_sign(raw, side_cache)
    if sign is None:
        return None
    base, quote = meta["base_symbol"], meta["quote_symbol"]
    qty = D(raw["quantity"]).copy_abs()
    height = int(raw["height"])
    trade_ms = fetch_ms - (live_h - height) * BLOCK_MS
    return {
        "external_trade_id": f"{raw.get('tx_hash')}:{raw.get('tx_index')}",
        "trade_date_ms": trade_ms,
        "signed_qty": qty * sign,
        "price": D(raw["price"]),
        "fee_amount": D(raw.get("fee", "0")),
        "fee_asset": quote,                       # fee_asset_id 2 = USDT (already USD)
        "base_asset": base,
        "source": "api",
        "venue": "NATIVE CORE",
        "counterparty": None,
        "comment": f"native h={height}",
    }, f"{base}/{quote}@{INSTR_VENUE}"


def native_fills(lookback_blocks: int = WINDOW):
    """(canonical_fills, n_raw, n_unsigned) available in the current window.
    Empty fills with n_raw>0 and n_unsigned>0 means some orders were pruned."""
    h = live_height()
    markets = markets_map()
    fetch_ms = int(time.time() * 1000)
    raw = fetch_window_fills(max(0, h - lookback_blocks), h)
    side_cache, out, unsigned = {}, [], 0
    for fl in raw:
        norm = normalize_fill(fl, markets, h, fetch_ms, side_cache)
        if norm is None:
            unsigned += 1
            continue
        fill, inst = norm
        fill["_instrument"] = inst
        out.append(fill)
    return out, len(raw), unsigned


def native_legs(lookback_blocks: int = WINDOW):
    """[(leg_labels, fills)] grouped by instrument, ready for the 8041 ingest.
    Empty list when no fills are in the window (the common case)."""
    fills, _, _ = native_fills(lookback_blocks)
    by_inst: dict[str, list] = {}
    for fl in fills:
        by_inst.setdefault(fl.pop("_instrument"), []).append(fl)
    legs = []
    for inst, fl in by_inst.items():
        quote = inst.split("/")[1].split("@")[0]
        legs.append((
            {"venue": "NATIVE CORE", "account": "TRADING_01@NATIVECORE",
             "instrument": inst, "product": "SPOT",
             "quote_asset": quote, "counterparty": None},
            fl,
        ))
    return legs


if __name__ == "__main__":
    fills, n_raw, n_unsigned = native_fills()
    print(f"live window: {n_raw} raw fills, {len(fills)} signed, {n_unsigned} unresolved")
    from collections import defaultdict
    agg = defaultdict(lambda: [D(0), D(0), 0])
    for fl in fills:
        a = agg[fl["_instrument"]]
        a[0] += fl["signed_qty"]
        a[1] += fl["fee_amount"]
        a[2] += 1
    for inst, (netq, fee, n) in sorted(agg.items()):
        print(f"  {inst:26s} {n:3d} fills  net_qty={float(netq):+.4f}  fees={float(fee):.4f} USDT")
