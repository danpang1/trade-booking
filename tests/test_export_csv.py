"""Tests for trade-booking/scripts/export_csv.py — pure-logic functions only."""
from __future__ import annotations
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import export_csv  # noqa: E402


# Fixture: minimal portfolios.json shape (the few keys we use)
PORTFOLIOS = [
    {"number": 8000, "name": "TOKKA LABS - MM PMM - RFQ"},
    {"number": 8041, "name": "TOKKA LABS - ALPHA"},
]


def _cashflow(**overrides):
    base = {
        "deal_ref": "MCF-1",
        "first_effective_start": "2026-05-10T09:00:00+00:00",
        "txn_type": "CASHFLOW",
        "cashflow_type": "TRANSFER",
        "direction": "INCOMING",
        "portfolio_id": "8041",
        "portfolio_name": "TOKKA LABS - ALPHA",
        "counterparty": "Coinbase",
        "asset": "USDT",
        "amount": "1000",
        "fee_asset": "USDT",
        "fee_amount": "1",
        "trade_date": "2026-05-19T08:42:00+00:00",
        "value_date": "2026-05-19T08:42:00+00:00",
        "account": "Coinbase · prime · main",
        "account_type": "BROKERAGE",
        "txid_reference": None,
        "comment": None,
    }
    base.update(overrides)
    return base


def _spot(**overrides):
    base = {
        "deal_ref": "MFX-7",
        "first_effective_start": "2026-05-19T08:42:00+00:00",
        "txn_type": "SPOT",
        "direction": "LONG",
        "portfolio_id": "8041",
        "portfolio_name": "TOKKA LABS - ALPHA",
        "counterparty": "Binance",
        "account": "Binance · spot · tk006",
        "account_type": "EXCHANGE",
        "base_asset": "BTC",
        "base_amount": "0.5",
        "quote_asset": "USDT",
        "quote_amount": "35000",
        "price": "70000",
        "fee_asset": "USDT",
        "fee_amount": "17.5",
        "trade_date": "2026-05-19T08:42:00+00:00",
        "value_date": "2026-05-19T08:42:00+00:00",
        "txid_reference": None,
        "comment": None,
    }
    base.update(overrides)
    return base


# ── §1: Column spec ──────────────────────────────────────────────

def test_blotter_columns_match_spec_exactly():
    assert export_csv.BLOTTER_COLUMNS == (
        "Input Date", "Month Year", "Deal Reference", "Portfolio",
        "Portfolio Name", "Counterparty", "Txn Type", "Trade Type",
        "Asset", "Amount", "Fee Asset", "Fee Amount",
        "Trade Date", "Value Date", "Account", "Account Type",
        "TXID/REFERENCE", "Comment",
    )


# ── §2: Month-year format ────────────────────────────────────────

def test_fmt_month_year_iso_with_tz():
    assert export_csv.fmt_month_year("2026-05-19T08:42:00+00:00") == "May 2026"


def test_fmt_month_year_none_returns_empty():
    assert export_csv.fmt_month_year(None) == ""


def test_fmt_month_year_garbage_returns_empty():
    assert export_csv.fmt_month_year("not a date") == ""


# ── §3: Cashflow → row ───────────────────────────────────────────

def test_cashflow_incoming_amount_positive():
    row = export_csv.cashflow_to_row(_cashflow(direction="INCOMING", amount="1000"),
                                     portfolios=PORTFOLIOS)
    assert row["Amount"] == "1000"


def test_cashflow_outgoing_amount_negative():
    row = export_csv.cashflow_to_row(_cashflow(direction="OUTGOING", amount="1000"),
                                     portfolios=PORTFOLIOS)
    assert row["Amount"] == "-1000"


def test_cashflow_outgoing_already_negative_left_alone():
    # Defensive: if DB ever stores a signed amount, don't double-flip.
    row = export_csv.cashflow_to_row(_cashflow(direction="OUTGOING", amount="-1000"),
                                     portfolios=PORTFOLIOS)
    assert row["Amount"] == "-1000"


def test_cashflow_input_date_uses_first_effective_start():
    row = export_csv.cashflow_to_row(
        _cashflow(first_effective_start="2026-05-10T09:00:00+00:00",
                  effective_start="2026-05-20T11:00:00+00:00"),
        portfolios=PORTFOLIOS,
    )
    assert row["Input Date"] == "2026-05-10T09:00:00+00:00"


def test_cashflow_txn_type_and_trade_type():
    row = export_csv.cashflow_to_row(_cashflow(cashflow_type="REBATE"),
                                     portfolios=PORTFOLIOS)
    assert row["Txn Type"] == "CASHFLOW"
    assert row["Trade Type"] == "REBATE"


def test_cashflow_inter_ptf_funding_counterparty_resolved_to_name():
    row = export_csv.cashflow_to_row(
        _cashflow(cashflow_type="INTER PTF FUNDING", counterparty="8000"),
        portfolios=PORTFOLIOS,
    )
    assert row["Counterparty"] == "TOKKA LABS - MM PMM - RFQ"


def test_cashflow_inter_ptf_funding_unknown_portfolio_falls_back():
    row = export_csv.cashflow_to_row(
        _cashflow(cashflow_type="INTER PTF FUNDING", counterparty="9999"),
        portfolios=PORTFOLIOS,
    )
    assert row["Counterparty"] == "9999"


def test_cashflow_non_inter_ptf_counterparty_untouched():
    row = export_csv.cashflow_to_row(
        _cashflow(cashflow_type="TRANSFER", counterparty="Coinbase"),
        portfolios=PORTFOLIOS,
    )
    assert row["Counterparty"] == "Coinbase"


def test_cashflow_all_expected_keys_present():
    row = export_csv.cashflow_to_row(_cashflow(), portfolios=PORTFOLIOS)
    assert set(row.keys()) == set(export_csv.BLOTTER_COLUMNS)


def test_cashflow_inter_ptf_funding_skips_malformed_portfolio_entries():
    """A bad entry mid-list must not abort the lookup for valid ones after it."""
    bad_portfolios = [
        {"number": "not-an-int", "name": "BAD"},
        {"number": 8000, "name": "TOKKA LABS - MM PMM - RFQ"},
    ]
    row = export_csv.cashflow_to_row(
        _cashflow(cashflow_type="INTER PTF FUNDING", counterparty="8000"),
        portfolios=bad_portfolios,
    )
    assert row["Counterparty"] == "TOKKA LABS - MM PMM - RFQ"


def test_cashflow_amount_nan_falls_back_to_raw_string():
    row = export_csv.cashflow_to_row(_cashflow(direction="INCOMING", amount="NaN"),
                                     portfolios=PORTFOLIOS)
    assert row["Amount"] == "NaN"


def test_cashflow_amount_infinity_falls_back_to_raw_string():
    row = export_csv.cashflow_to_row(_cashflow(direction="OUTGOING", amount="Infinity"),
                                     portfolios=PORTFOLIOS)
    assert row["Amount"] == "Infinity"


# ── §4: Spot → rows ──────────────────────────────────────────────

def test_spot_long_explodes_to_three_rows():
    rows = export_csv.spot_to_rows(_spot(direction="LONG"))
    assert len(rows) == 3
    assert (rows[0]["Asset"], rows[0]["Amount"]) == ("BTC", "0.5")
    assert (rows[1]["Asset"], rows[1]["Amount"]) == ("USDT", "-35000")
    assert (rows[2]["Asset"], rows[2]["Amount"]) == ("USDT", "-17.5")


def test_spot_short_explodes_with_flipped_signs_but_fee_stays_negative():
    rows = export_csv.spot_to_rows(_spot(direction="SHORT"))
    assert len(rows) == 3
    assert (rows[0]["Asset"], rows[0]["Amount"]) == ("BTC", "-0.5")
    assert (rows[1]["Asset"], rows[1]["Amount"]) == ("USDT", "35000")
    assert (rows[2]["Asset"], rows[2]["Amount"]) == ("USDT", "-17.5")


def test_spot_no_fee_drops_fee_row():
    rows = export_csv.spot_to_rows(_spot(fee_amount=None, fee_asset=None))
    assert len(rows) == 2


def test_spot_zero_fee_drops_fee_row():
    rows = export_csv.spot_to_rows(_spot(fee_amount="0"))
    assert len(rows) == 2


def test_spot_trade_type_is_direction():
    rows = export_csv.spot_to_rows(_spot(direction="LONG"))
    assert all(r["Trade Type"] == "LONG" for r in rows)


def test_spot_all_rows_share_deal_ref_and_input_date():
    rows = export_csv.spot_to_rows(_spot())
    assert {r["Deal Reference"] for r in rows} == {"MFX-7"}
    assert {r["Input Date"] for r in rows} == {"2026-05-19T08:42:00+00:00"}


def test_spot_base_quote_legs_have_empty_fee_columns():
    rows = export_csv.spot_to_rows(_spot())
    assert rows[0]["Fee Asset"] == "" and rows[0]["Fee Amount"] == ""
    assert rows[1]["Fee Asset"] == "" and rows[1]["Fee Amount"] == ""


def test_spot_fee_row_carries_fee_asset_and_amount():
    rows = export_csv.spot_to_rows(_spot())
    assert rows[2]["Fee Asset"] == "USDT"
    assert rows[2]["Fee Amount"] == "17.5"


# ── §5: CSV serialization ────────────────────────────────────────

def test_serialize_csv_emits_header_only_for_empty_rows():
    out = export_csv.serialize_csv([])
    lines = out.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("Input Date,Month Year,Deal Reference,")


def test_serialize_csv_quotes_comma_in_value():
    row = {h: "" for h in export_csv.BLOTTER_COLUMNS}
    row["Comment"] = "hello, world"
    out = export_csv.serialize_csv([row])
    assert '"hello, world"' in out


def test_serialize_csv_quotes_newline_in_value():
    row = {h: "" for h in export_csv.BLOTTER_COLUMNS}
    row["Comment"] = "line 1\nline 2"
    out = export_csv.serialize_csv([row])
    assert '"line 1\nline 2"' in out


def test_serialize_csv_one_full_row_round_trips():
    import csv as _csv
    import io
    row = export_csv.cashflow_to_row(_cashflow(), portfolios=PORTFOLIOS)
    out = export_csv.serialize_csv([row])
    rows = list(_csv.DictReader(io.StringIO(out)))
    assert len(rows) == 1
    assert rows[0]["Deal Reference"] == "MCF-1"
