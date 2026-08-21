"""Borrowable-USDT maths for the Binance VIP loan tile."""
import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "binance_vip_loan_ltv",
    Path(__file__).resolve().parent.parent / "scripts" / "binance_vip_loan_ltv.py",
)
vip = importlib.util.module_from_spec(_SPEC)
sys.modules["binance_vip_loan_ltv"] = vip
_SPEC.loader.exec_module(vip)


def test_borrowable_is_headroom_to_the_ltv_cap():
    # 100 of collateral supports 71 of debt; 60 is drawn, so 11 is left.
    assert vip._borrowable_usdt(100.0, 60.0, 0.71) == pytest.approx(11.0)


def test_borrowable_matches_account_818_snapshot():
    # Live 2026-08-21: collateral 30,709,646.44 against debt 20,554,787.80
    # at 66.93% LTV. Binance quotes ~1.2m drawable, not the 2,149,785.02 of
    # free collateral the tile used to show.
    got = vip._borrowable_usdt(30709646.44, 20554787.80, 0.71)
    assert got == pytest.approx(1249061.17, abs=0.01)


def test_borrowable_equals_debt_scaled_by_ltv_ratio():
    # Same figure from the other direction: debt * (target/current - 1),
    # which needs no collateral input at all.
    collateral, debt = 30709646.44, 20554787.80
    current_ltv = debt / collateral
    assert vip._borrowable_usdt(collateral, debt, 0.71) == pytest.approx(
        debt * (0.71 / current_ltv - 1), abs=0.01
    )


def test_borrowable_floors_at_zero_when_over_the_cap():
    # Above the cap there is no headroom, and the figure must not go negative.
    assert vip._borrowable_usdt(28000000.0, 20554787.80, 0.71) == 0.0


def test_borrowable_scales_with_initial_ltv():
    # An account whose orders are struck at a different initial LTV is
    # configured via BINANCE_INITIAL_LTV, not by moving the warning line.
    assert vip._borrowable_usdt(100.0, 0.0, 0.60) == pytest.approx(60.0)
    assert vip._borrowable_usdt(100.0, 0.0, 0.75) == pytest.approx(75.0)


def test_initial_ltv_is_independent_of_warn_ltv():
    assert vip.INITIAL_LTV == 0.71
    assert vip.MARGIN_CALL_LTV == 0.77
    assert vip.LIQUIDATION_LTV == 0.91
