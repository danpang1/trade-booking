"""Unit tests for the gateway account_id rule port (scripts/gateway_rule.py).

Pure — no DB. Guards the faithful port of T2X's gateway.rule.ts so a drift in
the suffix table or the alias/lowercase handling is caught in CI.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import gateway_rule as g  # noqa: E402


def test_exchange_product_suffixes():
    assert g.generate_trading_account_id(3, "exchange", "spot") == 3001
    assert g.generate_trading_account_id(3, "exchange", "trading") == 3001
    assert g.generate_trading_account_id(3, "exchange", "usdt_future") == 3002
    assert g.generate_trading_account_id(3, "exchange", "futures") == 3002
    assert g.generate_trading_account_id(3, "exchange", "coin_future") == 3003
    assert g.generate_trading_account_id(3, "exchange", "derivatives") == 3004
    assert g.generate_trading_account_id(3, "exchange", "portfolio_margin") == 3005
    assert g.generate_trading_account_id(3, "exchange", "funding") == 3006
    assert g.generate_trading_account_id(3, "exchange", "unified") == 3007
    assert g.generate_trading_account_id(3, "exchange", "alpha") == 3008


def test_hyperliquid_perp_suffixes():
    assert g.generate_trading_account_id(24, "exchange", "futures_xyz") == 24009
    assert g.generate_trading_account_id(24, "exchange", "futures_flx") == 24010
    assert g.generate_trading_account_id(24, "exchange", "futures_cash") == 24013


def test_broker_is_fixed_201():
    assert g.generate_trading_account_id(5, "broker", "trading") == 5201


def test_wallet_chain_suffixes():
    assert g.generate_trading_account_id(10, "wallet", "ethereum") == 10501
    assert g.generate_trading_account_id(10, "wallet", "solana") == 10701
    assert g.generate_trading_account_id(10, "wallet", "bitcoin") == 10801
    assert g.generate_trading_account_id(10, "wallet", "tron") == 10811
    assert g.generate_trading_account_id(10, "wallet", "shadow_simulation") == 10999


def test_suffix_aliases():
    # T2X-name -> gateway-suffix remaps (verbatim from generateTradingAccountId)
    assert g.generate_trading_account_id(10, "wallet", "BINANCE SMART CHAIN") == 10502
    assert g.generate_trading_account_id(10, "wallet", "BITCOIN CASH") == 10804


def test_case_insensitive():
    assert g.generate_trading_account_id(3, "EXCHANGE", "SPOT") == 3001
    assert g.generate_trading_account_id(10, "Wallet", "Ethereum") == 10501


def test_variable_length_t2x_id_is_prepended_as_is():
    # id length varies; suffix is always exactly the 3 rule digits
    assert g.generate_trading_account_id(3, "exchange", "spot") == 3001
    assert g.generate_trading_account_id(62, "exchange", "spot") == 62001
    assert g.generate_trading_account_id(218, "exchange", "spot") == 218001


def test_unknown_key_returns_none():
    assert g.generate_trading_account_id(3, "exchange", "no_such_product") is None
    assert g.generate_trading_account_id(3, "wallet", "spot") is None  # wrong category
    assert g.generate_trading_account_id(3, "bank", "trading") is None


def test_none_inputs_return_none():
    assert g.generate_trading_account_id(None, "exchange", "spot") is None
    assert g.generate_trading_account_id(3, None, "spot") is None
    assert g.generate_trading_account_id(3, "exchange", None) is None
