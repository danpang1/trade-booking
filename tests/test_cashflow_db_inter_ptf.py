"""Validation tests for INTER PTF FUNDING.

The frontend (TradeBookingForm.jsx:6312-6318) intentionally stores a portfolio
number string in `counterparty` when cashflow_type == "INTER PTF FUNDING" —
the picker swaps from CounterpartyPicker to PortfolioPicker. The backend must
mirror that swap and validate `counterparty` against the portfolios refdata
set, not the counterparties refdata set.

These tests pin that contract.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import cashflow_db  # noqa: E402


def _ipf_payload(counterparty: str = "8006") -> dict:
    """Inter-portfolio funding leg, sender side (8888 → 8006).

    Uses refdata-valid portfolios/account/asset. The only knob the test
    flexes is `counterparty` (the receiving portfolio number as a string).
    """
    return {
        "deal_ref": "MCF-PLACEHOLDER",
        "external_trade_id": None,
        "cashflow_type": "INTER PTF FUNDING",
        "direction": "OUTGOING",
        "entity": "TOKKA LABS PTE LTD",
        "portfolio_id": 8888,
        "portfolio_name": "TOKKA LABS - TREASURY",
        "counterparty": counterparty,
        "account": "TK818@BINANCE",
        "account_type": "EXCHANGE",
        "asset": "USDC",
        "amount": "-1234",
        "fee_asset": None,
        "fee_amount": "0",
        "trade_date": "2026-05-26T12:00:00Z",
        "value_date": "2026-05-26T12:00:00Z",
        "network": None,
        "txid_reference": None,
        "user_id": "test",
        "status": "PENDING",
        "comment": None,
    }


def test_ipf_accepts_valid_portfolio_number_as_counterparty():
    """8006 is a real portfolio number — must validate."""
    cashflow_db.validate_payload(_ipf_payload("8006"), mode="insert")


def test_ipf_rejects_unknown_portfolio_number_as_counterparty():
    """99999 isn't a portfolio — must fail with a portfolio-flavored message."""
    with pytest.raises(cashflow_db.ValidationError, match="portfolio"):
        cashflow_db.validate_payload(_ipf_payload("99999"), mode="insert")


def test_ipf_rejects_real_counterparty_name_as_counterparty():
    """A real refdata counterparty name (e.g. BEBOP LTD) is wrong for IPF —
    the field must be a portfolio number string. Must fail."""
    with pytest.raises(cashflow_db.ValidationError, match="portfolio"):
        cashflow_db.validate_payload(_ipf_payload("BEBOP LTD"), mode="insert")


def test_non_ipf_still_validates_against_counterparties_refdata():
    """Regression: non-IPF cashflow_types must still use counterparties refdata.
    A portfolio number in counterparty for OTHER INCOME must fail."""
    p = _ipf_payload("8006")
    p["cashflow_type"] = "OTHER INCOME"
    p["direction"] = "INCOMING"
    p["amount"] = "1234"
    with pytest.raises(cashflow_db.ValidationError, match="counterparty"):
        cashflow_db.validate_payload(p, mode="insert")
