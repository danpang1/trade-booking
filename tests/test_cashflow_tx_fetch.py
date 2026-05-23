"""Unit tests for cashflow_tx_fetch — pure logic, urllib.request.urlopen patched.

Manual smoke / integration test lives in the script's docstring (real Goldrush call).
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import cashflow_tx_fetch  # noqa: E402


# ── §1: Chain mapping ────────────────────────────────────────────

def test_chains_has_25_entries():
    assert len(cashflow_tx_fetch.CHAINS) == 25


def test_chains_each_entry_has_chain_name_and_native_asset():
    for name, info in cashflow_tx_fetch.CHAINS.items():
        assert isinstance(name, str) and name == name.upper(), name
        assert "chain_name" in info and isinstance(info["chain_name"], str)
        assert "native_asset" in info and isinstance(info["native_asset"], str)


def test_chains_known_entries():
    assert cashflow_tx_fetch.CHAINS["ETHEREUM"] == {
        "chain_name": "eth-mainnet",
        "native_asset": "ETH",
    }
    assert cashflow_tx_fetch.CHAINS["BINANCE SMART CHAIN"] == {
        "chain_name": "bsc-mainnet",
        "native_asset": "BNB",
    }
    assert cashflow_tx_fetch.CHAINS["ARBITRUM"] == {
        "chain_name": "arbitrum-mainnet",
        "native_asset": "ETH",
    }


import pytest  # noqa: E402


# ── §2: Input validation ─────────────────────────────────────────

VALID_HASH = "0x" + "a" * 64


def test_validate_input_accepts_valid_hash_and_network():
    out = cashflow_tx_fetch.validate_input(
        {"tx_hash": VALID_HASH, "network": "ETHEREUM"}
    )
    assert out["tx_hash"] == VALID_HASH.lower()
    assert out["network"] == "ETHEREUM"


def test_validate_input_lowercases_hex():
    out = cashflow_tx_fetch.validate_input(
        {"tx_hash": "0x" + "A" * 64, "network": "BASE"}
    )
    assert out["tx_hash"] == "0x" + "a" * 64


@pytest.mark.parametrize("bad_hash", [
    "",
    "0x123",                  # too short
    "0x" + "z" * 64,          # non-hex
    "a" * 66,                 # missing 0x prefix
    "0x" + "a" * 65,          # too long
    None,
])
def test_validate_input_rejects_bad_hash(bad_hash):
    with pytest.raises(cashflow_tx_fetch.ValidationError):
        cashflow_tx_fetch.validate_input({"tx_hash": bad_hash, "network": "ETHEREUM"})


@pytest.mark.parametrize("bad_network", [
    "",
    None,
    "SOLANA",         # non-EVM, not in CHAINS
    "BITCOIN",        # non-EVM
    "ethereum",       # case matters — we standardised on uppercase keys
    "MADE_UP_CHAIN",
])
def test_validate_input_rejects_bad_network(bad_network):
    with pytest.raises(cashflow_tx_fetch.ValidationError):
        cashflow_tx_fetch.validate_input({"tx_hash": VALID_HASH, "network": bad_network})


def test_validate_input_rejects_missing_keys():
    with pytest.raises(cashflow_tx_fetch.ValidationError):
        cashflow_tx_fetch.validate_input({"tx_hash": VALID_HASH})  # no network
    with pytest.raises(cashflow_tx_fetch.ValidationError):
        cashflow_tx_fetch.validate_input({"network": "ETHEREUM"})  # no hash


def test_validation_error_carries_message():
    with pytest.raises(cashflow_tx_fetch.ValidationError, match=r"hash"):
        cashflow_tx_fetch.validate_input({"tx_hash": "nope", "network": "ETHEREUM"})
