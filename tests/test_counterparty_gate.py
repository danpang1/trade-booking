"""The counterparty gate: a named counterparty must be an exact refdata name
and its CID is stamped server-side, on every book.

Before 2026-09-30 only cashflows checked the name, none of the three books
stamped counterparty_id (the form did it client-side), so anything booked
through the API -- the Slack bot above all -- could carry free text and
arrive with no CID.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import cashflow_db  # noqa: E402
import spot_db  # noqa: E402
import loan_db  # noqa: E402


@pytest.fixture(autouse=True)
def _stub_refdata(monkeypatch):
    monkeypatch.setattr(cashflow_db, "_load_counterparties_map",
                        lambda: {"BINANCE INVESTMENTS CO. LTD": 177, "DINARI": 202, "KRAKEN": 166})
    monkeypatch.setattr(cashflow_db, "_load_counterparties_set",
                        lambda: {"BINANCE INVESTMENTS CO. LTD", "DINARI", "KRAKEN"})
    monkeypatch.setattr(cashflow_db, "_load_portfolio_ids_set", lambda: {8041, 8888})
    monkeypatch.setattr(cashflow_db, "_load_accounts_set", lambda: set())
    monkeypatch.setattr(cashflow_db, "_load_assets_set", lambda: set())


def test_format_cid():
    assert cashflow_db.format_cid(177) == "CID000177"
    assert cashflow_db.format_cid("5") == "CID000005"
    assert cashflow_db.format_cid("cid000202") == "CID000202"
    assert cashflow_db.format_cid(None) is None
    assert cashflow_db.format_cid("") is None


def test_stamp_overrides_whatever_the_client_sent():
    p = {"counterparty": "DINARI", "counterparty_id": "CID999999"}
    cashflow_db.stamp_counterparty(p)
    assert p["counterparty_id"] == "CID000202"


def test_free_text_is_rejected_with_a_hint():
    with pytest.raises(cashflow_db.ValidationError, match="did you mean 'DINARI'"):
        cashflow_db.stamp_counterparty({"counterparty": "dinari"})
    with pytest.raises(cashflow_db.ValidationError, match="free text is not accepted"):
        cashflow_db.stamp_counterparty({"counterparty": "Dinari Inc"})


def test_portfolio_number_only_where_allowed():
    p = {"counterparty": "8888", "counterparty_id": "CID000001"}
    cashflow_db.stamp_counterparty(p, allow_portfolio=True)
    assert p["counterparty_id"] is None
    with pytest.raises(cashflow_db.ValidationError, match="not in refdata"):
        cashflow_db.stamp_counterparty({"counterparty": "9999"}, allow_portfolio=True)
    with pytest.raises(cashflow_db.ValidationError, match="free text"):
        cashflow_db.stamp_counterparty({"counterparty": "8888"})


def test_blank_counterparty_is_left_alone():
    p = {"counterparty": None, "counterparty_id": None}
    cashflow_db.stamp_counterparty(p)
    assert p == {"counterparty": None, "counterparty_id": None}


def test_fails_open_when_refdata_unreadable(monkeypatch):
    monkeypatch.setattr(cashflow_db, "_load_counterparties_map", lambda: (_ for _ in ()).throw(FileNotFoundError()))
    p = {"counterparty": "ANYONE", "counterparty_id": None}
    cashflow_db.stamp_counterparty(p)
    assert p["counterparty_id"] is None


def _spot(**over):
    p = {
        "direction": "LONG", "entity": "TOKKA LABS", "portfolio_id": 8041, "portfolio_name": "CRB",
        "base_asset": "SPCX", "base_amount": "1", "quote_asset": "USDC", "quote_amount": "150",
        "price": "150", "trade_date": "2026-09-30T00:00:00+00:00", "value_date": "2026-09-30T00:00:00+00:00",
        "user_id": "bot", "status": "CONFIRMED", "counterparty": "DINARI", "counterparty_id": None,
    }
    p.update(over)
    return p


def test_spot_stamps_cid_and_rejects_free_text():
    p = _spot()
    spot_db.validate_payload(p, mode="insert")
    assert p["counterparty_id"] == "CID000202"
    with pytest.raises(spot_db.ValidationError, match="not in refdata"):
        spot_db.validate_payload(_spot(counterparty="Dinari"), mode="insert")
    q = _spot(counterparty="8888")
    spot_db.validate_payload(q, mode="insert")
    assert q["counterparty_id"] is None


def _loan(**over):
    p = {
        "direction": "BORROW", "loan_type": "VIP LOAN", "entity": "TOKKA LABS", "portfolio_id": 8888,
        "portfolio_name": "TREASURY", "principal_asset": "USDT", "principal_amount": "1000",
        "interest_asset": "USDT", "interest_type": "FIXED", "trade_date": "2026-09-30T00:00:00+00:00",
        "user_id": "bot", "status": "LIVE", "counterparty": "KRAKEN", "counterparty_id": None,
    }
    p.update(over)
    return p


def test_loan_stamps_cid_and_rejects_free_text():
    p = _loan()
    loan_db.validate_payload(p, mode="insert")
    assert p["counterparty_id"] == "CID000166"
    with pytest.raises(loan_db.ValidationError, match="not in refdata"):
        loan_db.validate_payload(_loan(counterparty="Kraken Ltd"), mode="insert")
    with pytest.raises(loan_db.ValidationError, match="free text"):
        loan_db.validate_payload(_loan(counterparty="8888"), mode="insert")
