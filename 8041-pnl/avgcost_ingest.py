"""Pure avg-cost fold + venue fee normalization for trades_spot_avgcost.

No DB or network here — pure functions so they unit-test without psycopg2 or
venue creds. The DB layer (avgcost_db.py) and the runner (pnl_8041_daily.py)
call into these.
"""
from __future__ import annotations
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
from engine import Position, apply_fill, D  # noqa: E402


def fee_to_usd(fee_amount, fee_asset, base_asset, price):
    """Convert a raw fill fee to USD.

    HL in-kind fees are charged in the base token (e.g. SPCXD); value them at
    the fill price. Everything else (USDT/USDC commissions) is already USD.
    """
    fee = D(fee_amount)
    if fee_asset and base_asset and fee_asset.upper() == base_asset.upper():
        return fee * D(price)
    return fee


def fold_fills(seed_qty, seed_avg, fills):
    """Replay ordered `fills` onto a Position seeded at (seed_qty, seed_avg).

    Each fill is a dict with at least signed_qty, price, fee_amount,
    fee_asset, base_asset. Returns NEW dicts = each input plus realized,
    pos_qty_after, avg_cost_after, fee_usd. Caller must pass fills in
    (trade_date, ext_id) order with DB-present fills already removed.

    In-kind fees (fee_asset == base_asset, e.g. HL/Native buys) are folded
    NET: the position receives signed_qty − fee, so the memoized position
    always ties to the venue/custody balance. fee_usd stays as the explicit
    expense line (cost basis adds net_qty × px while cash paid qty × px —
    the difference IS fee_usd, so nothing is double-counted). 2026-07-02.
    """
    pos = Position(D(seed_qty), D(seed_avg))
    out = []
    for f in fills:
        sq = D(f["signed_qty"])
        fee = D(f.get("fee_amount", 0) or 0)
        fa, ba = f.get("fee_asset"), f.get("base_asset")
        if fee and fa and ba and fa.upper() == ba.upper():
            sq -= fee                      # tokens settled net of in-kind fee
        res = apply_fill(pos, sq, D(f["price"]))
        row = dict(f)
        row["realized"] = res.realized
        row["pos_qty_after"] = pos.qty
        row["avg_cost_after"] = pos.avg_cost
        row["fee_usd"] = fee_to_usd(
            f.get("fee_amount", 0), f.get("fee_asset"),
            f.get("base_asset"), f["price"],
        )
        out.append(row)
    return out


def refold_rows(rows):
    """Recompute realized / pos_qty_after / avg_cost_after for ALL rows of a
    leg by replaying them from a flat position in chronological
    (trade_date_ms, external_trade_id) order.

    Repairs legs whose memoized running position was written out of order by an
    incremental top-up that appended a back-dated fill after later ones (the
    SPCXD Dinari-bridge bug). Returns new dicts in chronological order.
    """
    ordered = sorted(rows, key=lambda r: (r["trade_date_ms"],
                                          str(r["external_trade_id"])))
    return fold_fills(D(0), D(0), ordered)


def needs_refold(tip_key, fresh_fills):
    """True if any fresh fill sorts before the current stored tip.

    `tip_key` = (trade_date_ms, external_trade_id) of the leg's latest stored
    fill, or None for an empty leg. A fresh fill that predates the tip cannot be
    folded by seeding from the tip — it would mis-order history and corrupt the
    memoized running position — so the whole leg must be re-folded instead.
    """
    if tip_key is None:
        return False
    return any((f["trade_date_ms"], str(f["external_trade_id"])) < tip_key
               for f in fresh_fills)
