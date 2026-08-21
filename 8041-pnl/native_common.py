"""Native Core (/info) shared layer for the 8041 PnL toolkit.

Native Core is the spot-credit DEX exposing a single read-only `POST /info`
gateway, user keyed by wallet address. The TRADING_01@NATIVECORE wallet holds
the central-risk-book legs (long SPCXB, short tokenized equities), the mirror of
8041's HL `xyz:*` perp shorts — so it folds into the 8041 PnL.

Two hard data constraints shape everything downstream (see also the
project_native_core_integration memory):

  1. `userFills` is queryable only for the MOST RECENT ~10,000 blocks (sliding
     window, inclusive [from_height, to_height], <=10k span). Older fills are
     pruned by the node and CANNOT be backfilled.
  2. `spotCreditPositions` gives settled qty (`actual_display`) but NO avg
     entry / cost basis, so cost basis cannot be reconstructed from positions.

=> "since inception" avg-cost is impossible from Native alone. The collector
must poll continuously to accumulate fills going forward; historical days are
covered only by snapshot mark-to-market (native_pnl_snapshot.py).

This module holds the bits both the forward collector and the snapshot-MTM
report share: the /info client, account identity, the live markets map, and the
Native-symbol -> HL `xyz:` perp mark mapping (the agreed mark source).
"""
from __future__ import annotations
import json
import urllib.error
import urllib.request
from decimal import Decimal

NATIVE_API = "https://api.native.org"
WALLET = "0xe71b2e6ddc88ffdecdcd0d750c57d0122aa586c2"
EXCH = "NATIVE CORE"
INSTR_VENUE = "NATIVECORE"
ACCOUNT_ID = 214004
ACCOUNT_NAME = "TRADING_01@NATIVECORE"

# Native settled-position symbol -> HL `xyz:` perp instrument used as its EOD
# mark (user decision: reuse 8041's existing HL perp marks for the matching
# underlying). USDT is the cash/credit counter-leg and carries no mark.
SYMBOL_TO_HL = {
    "SPCXB": "xyz:SPCX-P/USD@HYPERLIQUID_FUTURES",
    "TSLAB": "xyz:TSLA-P/USD@HYPERLIQUID_FUTURES",
    "CRCLB": "xyz:CRCL-P/USD@HYPERLIQUID_FUTURES",
    "NVDAB": "xyz:NVDA-P/USD@HYPERLIQUID_FUTURES",
    "SNDKB": "xyz:SNDK-P/USD@HYPERLIQUID_FUTURES",
    "MUB": "xyz:MU-P/USD@HYPERLIQUID_FUTURES",
}
CASH_SYMBOLS = {"USDT", "USDC", "USD"}


def post_info(body: dict, timeout: int = 25) -> dict:
    """POST one /info query (read-only, no auth) with light 429/5xx retry."""
    data = json.dumps(body).encode("utf-8")
    last = None
    for attempt in range(5):
        req = urllib.request.Request(
            f"{NATIVE_API}/info", data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                continue
            raise
    raise last


def live_height() -> int:
    """Current node query_height (used to derive a fresh userFills window)."""
    return int(post_info({"type": "openOrders", "user": WALLET, "market_id": "0"})["query_height"])


def markets_map() -> dict[int, dict]:
    """{market_id -> market meta} from the live `markets` query. meta carries
    base_symbol, quote_symbol, price_decimals, base_quantity_decimals — used to
    decode a fill's integer-atom price/qty."""
    out = {}
    for m in post_info({"type": "markets"}).get("markets", []):
        out[int(m["market_id"])] = m
    return out


def hl_instrument_for(symbol: str) -> str | None:
    """Native base symbol -> HL `xyz:` perp instrument for its mark, or None
    (cash legs / unmapped symbols have no reusable HL mark)."""
    return SYMBOL_TO_HL.get(symbol.upper())


def D(x) -> Decimal:
    if x is None or x == "":
        return Decimal("0")
    return x if isinstance(x, Decimal) else Decimal(str(x))
