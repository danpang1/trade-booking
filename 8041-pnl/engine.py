"""Avg-cost trade-basis PnL engine.

Implements the canonical methodology from the Tokka MO PnL spec:

  Daily PnL = Realized + delta_Unrealized + Fees + Funding + Interest + Rebates + Non-cash

Uses Decimal for all price/qty arithmetic. Applies weighted-average cost
convention with sign-flip handling (close old basis, open new at fill price).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, getcontext
from typing import Iterable

getcontext().prec = 40
ZERO = Decimal("0")


def D(x) -> Decimal:
    if isinstance(x, Decimal):
        return x
    if x is None:
        return ZERO
    return Decimal(str(x))


@dataclass
class Position:
    qty: Decimal = ZERO
    avg_cost: Decimal = ZERO  # for shorts: short-entry basis


@dataclass
class FillResult:
    realized: Decimal
    new_qty: Decimal
    new_avg_cost: Decimal
    split: bool = False  # True if a sign-flip split was applied


def apply_fill(pos: Position, qty_signed: Decimal, price: Decimal) -> FillResult:
    """Apply one fill (positive qty = buy, negative = sell) to a position.

    Returns realized leg PnL and updated position state. Mutates `pos` in place.
    Handles long, short, and sign-flip cases per the spec.
    """
    qty_signed = D(qty_signed)
    price = D(price)
    old_qty = pos.qty
    old_avg = pos.avg_cost

    if qty_signed == ZERO:
        return FillResult(ZERO, old_qty, old_avg)

    # Case A: opening or adding to a position in the same direction
    same_direction = (old_qty >= ZERO and qty_signed > ZERO) or (old_qty <= ZERO and qty_signed < ZERO)
    if same_direction or old_qty == ZERO:
        new_qty = old_qty + qty_signed
        if new_qty == ZERO:
            pos.qty = ZERO
            pos.avg_cost = ZERO
            return FillResult(ZERO, ZERO, ZERO)
        # weighted-average: for shorts, old_qty < 0 and qty_signed < 0 so abs cancels correctly
        pos.qty = new_qty
        pos.avg_cost = (old_qty * old_avg + qty_signed * price) / new_qty if old_qty != ZERO else price
        if old_qty == ZERO:
            pos.avg_cost = price
        return FillResult(ZERO, pos.qty, pos.avg_cost)

    # Reducing or flipping
    if abs(qty_signed) <= abs(old_qty):
        # Pure reduction: avg_cost unchanged; realize on closed qty
        closed_qty = -qty_signed  # positive magnitude actually closed
        # For long: closed_qty>0, realized = (price - avg) * closed_qty
        # For short: old_qty<0, qty_signed>0 (buy to cover), closed_qty = -qty_signed < 0
        #   realized_short = (avg - price) * |closed| = (avg - price) * (-closed_qty)
        # Unified: realized = (price - avg) * (-qty_signed) when long; (avg - price) * qty_signed when short
        if old_qty > ZERO:
            realized = (price - old_avg) * (-qty_signed)  # qty_signed<0
        else:
            realized = (old_avg - price) * qty_signed  # qty_signed>0, old_qty<0
        pos.qty = old_qty + qty_signed
        # avg_cost unchanged on reduction
        if pos.qty == ZERO:
            pos.avg_cost = ZERO
        return FillResult(realized, pos.qty, pos.avg_cost)

    # Sign-flip: close old_qty entirely, open residual at fill price
    # Leg (a): close old_qty at price
    if old_qty > ZERO:
        realized = (price - old_avg) * old_qty
    else:
        realized = (old_avg - price) * (-old_qty)
    residual = qty_signed + old_qty  # remaining after closing old position
    pos.qty = residual
    pos.avg_cost = price
    return FillResult(realized, pos.qty, pos.avg_cost, split=True)


def unrealized(pos: Position, mark: Decimal) -> Decimal:
    """MTM of the current position at `mark`. Works for long (qty>0) and short (qty<0)."""
    mark = D(mark)
    if pos.qty == ZERO:
        return ZERO
    if pos.qty > ZERO:
        return (mark - pos.avg_cost) * pos.qty
    return (pos.avg_cost - mark) * (-pos.qty)


@dataclass
class DayBucket:
    """Accumulates PnL components for one (asset, venue, account, product) day."""
    realized: Decimal = ZERO
    fees: Decimal = ZERO
    funding: Decimal = ZERO
    interest: Decimal = ZERO
    rebates: Decimal = ZERO
    non_cash: Decimal = ZERO
    trade_count: int = 0
    notes: list = field(default_factory=list)

    def total(self, delta_unrealized: Decimal) -> Decimal:
        return (self.realized + delta_unrealized + self.fees + self.funding
                + self.interest + self.rebates + self.non_cash)
