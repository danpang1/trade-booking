"""Pure-logic tests for 8041-pnl/avgcost_ingest.py (no DB / no network)."""
from pathlib import Path
import sys
from decimal import Decimal

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "8041-pnl"))

import avgcost_ingest as ing  # noqa: E402

D = Decimal


def _fill(qty, px, fee=0, fee_asset="USDT", base="SPCX", ext="x", src="api"):
    return {
        "external_trade_id": ext,
        "trade_date_ms": 0,
        "signed_qty": D(str(qty)),
        "price": D(str(px)),
        "fee_amount": D(str(fee)),
        "fee_asset": fee_asset,
        "base_asset": base,
        "source": src,
    }


def test_fee_to_usd_inkind_valued_at_price():
    # SPCXD fee on a SPCXD trade priced at 2.0 -> fee * price
    got = ing.fee_to_usd(D("3"), "SPCXD", "SPCXD", D("2.0"))
    assert got == D("6.0")


def test_fee_to_usd_usd_passthrough():
    got = ing.fee_to_usd(D("1.5"), "USDT", "SPCX", D("199.0"))
    assert got == D("1.5")


def test_fold_from_flat_two_buys_averages_cost():
    fills = [_fill(10, 100), _fill(10, 120)]
    rows = ing.fold_fills(D("0"), D("0"), fills)
    assert rows[0]["pos_qty_after"] == D("10")
    assert rows[0]["avg_cost_after"] == D("100")
    assert rows[1]["pos_qty_after"] == D("20")
    assert rows[1]["avg_cost_after"] == D("110")
    assert rows[0]["realized"] == D("0")


def test_fold_resumes_from_seed():
    # seed long 20 @ 110, then sell 5 @ 130 -> realized (130-110)*5 = 100
    rows = ing.fold_fills(D("20"), D("110"), [_fill(-5, 130)])
    assert rows[0]["realized"] == D("100")
    assert rows[0]["pos_qty_after"] == D("15")
    assert rows[0]["avg_cost_after"] == D("110")


def test_fold_short_then_cover():
    # open short 10 @ 100, cover 10 @ 90 -> realized (100-90)*10 = 100
    rows = ing.fold_fills(D("0"), D("0"), [_fill(-10, 100), _fill(10, 90)])
    assert rows[0]["pos_qty_after"] == D("-10")
    assert rows[1]["realized"] == D("100")
    assert rows[1]["pos_qty_after"] == D("0")


def test_fold_sign_flip():
    # long 5 @ 100, sell 8 @ 120: close 5 (realized (120-100)*5=100), open short 3 @ 120
    rows = ing.fold_fills(D("0"), D("0"), [_fill(5, 100), _fill(-8, 120)])
    assert rows[1]["realized"] == D("100")
    assert rows[1]["pos_qty_after"] == D("-3")
    assert rows[1]["avg_cost_after"] == D("120")


def test_fold_does_not_mutate_input():
    fills = [_fill(1, 100)]
    before = dict(fills[0])
    ing.fold_fills(D("0"), D("0"), fills)
    assert fills[0] == before
    assert "realized" not in fills[0]


def test_fold_computes_fee_usd_inkind():
    rows = ing.fold_fills(D("0"), D("0"),
                          [_fill(2, 50, fee="0.1", fee_asset="SPCXD", base="SPCXD")])
    assert rows[0]["fee_usd"] == D("5.0")  # 0.1 * 50


def _tf(ms, ext, qty, px):
    f = _fill(qty, px, ext=ext)
    f["trade_date_ms"] = ms
    return f


def test_refold_replays_in_chronological_order_regardless_of_input_order():
    # Rows handed in NON-chronological order, as a buggy incremental top-up
    # leaves them when a back-dated add is appended after later fills.
    rows = [_tf(3000, "c", -50, 12), _tf(1000, "a", 100, 10), _tf(2000, "b", 400, 9)]
    folded = ing.refold_rows(rows)
    assert [r["external_trade_id"] for r in folded] == ["a", "b", "c"]


def test_refold_tip_equals_total_signed_qty():
    # Running position after the last chronological fill = net of all signed
    # qty (order-independent) — the property the out-of-order memo violated
    # (SPCXD showed 4,018 instead of 4,421).
    rows = [_tf(3000, "c", -50, 12), _tf(1000, "a", 100, 10), _tf(2000, "b", 400, 9)]
    folded = ing.refold_rows(rows)
    assert folded[0]["pos_qty_after"] == D("100")
    assert folded[1]["pos_qty_after"] == D("500")
    assert folded[2]["pos_qty_after"] == D("450")   # 100 + 400 - 50


def test_needs_refold_true_when_a_fresh_fill_predates_the_stored_tip():
    assert ing.needs_refold((2000, "b"), [_tf(1500, "z", 10, 5)]) is True


def test_needs_refold_false_when_all_fresh_fills_are_after_the_tip():
    assert ing.needs_refold((2000, "b"),
                            [_tf(2500, "z", 10, 5), _tf(9000, "y", 1, 5)]) is False


def test_needs_refold_false_on_an_empty_leg():
    assert ing.needs_refold(None, [_tf(1, "z", 1, 5)]) is False
