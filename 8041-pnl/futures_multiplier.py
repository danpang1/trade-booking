"""Contract multiplier (point value) for CME futures — a maintained lookup.

Why hardcoded: neither of the data sources this toolkit uses exposes the CME
contract-definition schema.
  * ClickHouse `production.databento_{quote,trade}` carry market data only
    (bid/ask/size + symbols) — no contract_multiplier / display_factor.
  * The IBKR MCP (search_contracts / search_futures / get_price_snapshot)
    returns the contract ladder and live marks, but NO multiplier field.
So the multiplier comes from the CME contract spec, kept here. Keyed by product
ROOT (the exchange_symbol minus its month+year code, e.g. MNQU6 -> MNQ).

Multiplier = USD value of one full index/price point per contract. It is NOT the
tick value (tick value = multiplier * min tick). For MTM / unrealized use the
multiplier: unrealized = (entry - mark) * multiplier * signed_contracts.

Sources: CME contract specifications (cmegroup.com). Add rows as new roots trade;
`multiplier()` returns None for an unknown root so callers can fail loudly rather
than mark with a wrong point value.
"""
from __future__ import annotations

import re
from decimal import Decimal

# CME futures month codes, in the trailing {month}{year} contract code.
_MONTH = "FGHJKMNQUVXZ"
_CODE_RE = re.compile(r"^(.*?)([" + _MONTH + r"])(\d{1,2})$")

# Product ROOT -> USD point value (multiplier). CME contract specs.
CME_MULTIPLIER = {
    # --- Equity index: micros ($/pt) ---
    "MNQ": Decimal("2"),      # Micro E-mini Nasdaq-100
    "MES": Decimal("5"),      # Micro E-mini S&P 500
    "MYM": Decimal("0.5"),    # Micro E-mini Dow ($0.50/pt)
    "M2K": Decimal("5"),      # Micro E-mini Russell 2000
    # --- Equity index: E-minis ---
    "NQ": Decimal("20"),      # E-mini Nasdaq-100
    "ES": Decimal("50"),      # E-mini S&P 500
    "YM": Decimal("5"),       # E-mini Dow
    "RTY": Decimal("50"),     # E-mini Russell 2000
}


def root_of(symbol):
    """Product root from a futures symbol: strip a trailing {month}{year} code.
    MNQU6 / MNQU26 -> MNQ; M2KH7 -> M2K; a bare root (MNQ) is returned as-is."""
    s = str(symbol).upper().strip()
    m = _CODE_RE.match(s)
    return m.group(1) if m else s


def multiplier(symbol):
    """USD point value for a CME futures `symbol` (outright or bare root), or
    None if the root is not in the maintained table (caller should fail loudly)."""
    return CME_MULTIPLIER.get(root_of(symbol))


if __name__ == "__main__":
    for s in ("MNQU6", "MNQU26", "ESZ6", "M2KH7", "MYMM6", "NQU6", "MES", "XYZ9"):
        print(f"{s:8} root={root_of(s):5} multiplier={multiplier(s)}")
