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


def test_borrowable_applies_initial_ltv_to_free_collateral():
    # Free collateral is a collateral value; only initial_ltv of it can be
    # drawn as USDT. Returning the free collateral itself was the bug.
    assert vip._borrowable_usdt(100.0, 60.0, 0.71) == pytest.approx(28.4)


def test_borrowable_matches_account_818_snapshot():
    # Live 2026-08-21 figures: the tile showed the 2,144,518.70 of free
    # collateral as if it were drawable USDT.
    got = vip._borrowable_usdt(30701400.85, 28556882.15, 0.71)
    assert got == pytest.approx(1522608.28, abs=0.01)


def test_borrowable_floors_at_zero_when_fully_locked():
    # Collateral can sit below locked after an adverse mark; never negative.
    assert vip._borrowable_usdt(28000000.0, 28556882.15, 0.71) == 0.0


def test_borrowable_scales_with_initial_ltv():
    # An account whose orders are struck at a different initial LTV is
    # configured via BINANCE_INITIAL_LTV, not by moving the warning line.
    assert vip._borrowable_usdt(100.0, 0.0, 0.60) == pytest.approx(60.0)
    assert vip._borrowable_usdt(100.0, 0.0, 0.75) == pytest.approx(75.0)


def test_initial_ltv_is_independent_of_warn_ltv():
    assert vip.INITIAL_LTV == 0.71
    assert vip.MARGIN_CALL_LTV == 0.77
    assert vip.LIQUIDATION_LTV == 0.91
