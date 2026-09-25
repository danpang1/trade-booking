"""Unit tests for baking the gateway product/chain into the stored account name.

spot_db / cashflow_db.payload_to_columns store the account as "<name>_<PRODUCT>"
so a read can separate the sub-account. Pure — no DB.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import cashflow_db  # noqa: E402
import spot_db  # noqa: E402


def _acct(cols, vals):
    return dict(zip(cols, vals))["account"]


def test_spot_account_gets_product_suffix():
    cols, vals = spot_db.payload_to_columns(
        {"account": "ECT001@BINANCE", "product": "spot", "portfolio_id": "1"}
    )
    assert _acct(cols, vals) == "ECT001@BINANCE_SPOT"


def test_spot_account_multiword_product():
    cols, vals = spot_db.payload_to_columns(
        {"account": "ECT001@BINANCE", "product": "usdt_future", "portfolio_id": "1"}
    )
    assert _acct(cols, vals) == "ECT001@BINANCE_USDT_FUTURE"


def test_spot_no_product_keeps_bare_account():
    cols, vals = spot_db.payload_to_columns(
        {"account": "ECT001@BINANCE", "portfolio_id": "1"}
    )
    assert _acct(cols, vals) == "ECT001@BINANCE"


def test_spot_idempotent_when_already_suffixed():
    cols, vals = spot_db.payload_to_columns(
        {"account": "ECT001@BINANCE_SPOT", "product": "spot", "portfolio_id": "1"}
    )
    assert _acct(cols, vals) == "ECT001@BINANCE_SPOT"


def test_cashflow_account_gets_product_suffix():
    cols, vals = cashflow_db.payload_to_columns(
        {"account": "MM@ETH", "product": "ethereum", "portfolio_id": "1"}
    )
    assert _acct(cols, vals) == "MM@ETH_ETHEREUM"


def test_cashflow_no_product_keeps_bare_account():
    cols, vals = cashflow_db.payload_to_columns(
        {"account": "MM@ETH", "portfolio_id": "1"}
    )
    assert _acct(cols, vals) == "MM@ETH"
