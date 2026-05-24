"""Unit tests for cashflow_tx_fetch — pure logic, urllib.request.urlopen patched.

Manual smoke / integration test lives in the script's docstring (real Goldrush call).
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import cashflow_tx_fetch  # noqa: E402
import io  # noqa: E402
import json as _json  # noqa: E402
from urllib.error import HTTPError, URLError  # noqa: E402


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


# ── §3: Goldrush response parsing — single ERC-20 transfer ────────

# Trimmed shape of the Goldrush /v1/{chain}/transaction_v2/{hash}/ response
# for a 100 USDT transfer on Ethereum mainnet. Field names match Covalent docs.
USDT_TRANSFER_FIXTURE = {
    "data": {
        "items": [{
            "block_signed_at": "2026-05-22T14:23:11Z",
            "block_height": 19234567,
            "tx_hash": "0x" + "a" * 64,
            "from_address": "0x1111111111111111111111111111111111111111",
            "to_address": "0xdac17f958d2ee523a2206206994597c13d831ec7",  # USDT contract
            "value": "0",
            "gas_spent": 65000,
            "gas_price": 20_000_000_000,  # 20 gwei
            "log_events": [{
                "sender_contract_decimals": 6,
                "sender_contract_ticker_symbol": "USDT",
                "sender_address": "0xdac17f958d2ee523a2206206994597c13d831ec7",
                "decoded": {
                    "name": "Transfer",
                    "signature": "Transfer(indexed address from, indexed address to, uint256 value)",
                    "params": [
                        {"name": "from", "type": "address", "value": "0x1111111111111111111111111111111111111111"},
                        {"name": "to", "type": "address", "value": "0x2222222222222222222222222222222222222222"},
                        {"name": "value", "type": "uint256", "value": "100000000"},  # 100 * 10^6
                    ],
                },
            }],
        }],
    },
}


def test_parse_single_erc20_transfer():
    out = cashflow_tx_fetch.parse_goldrush(USDT_TRANSFER_FIXTURE, "ETHEREUM")
    assert out["transfers"] == [{
        "asset": "USDT",
        "amount": "100.000000",
        "from": "0x1111111111111111111111111111111111111111",
        "to": "0x2222222222222222222222222222222222222222",
        "decimals": 6,
        "contract_address": "0xdac17f958d2ee523a2206206994597c13d831ec7",
    }]
    assert out["gas_asset"] == "ETH"
    assert out["timestamp"] == "2026-05-22T14:23:11Z"
    assert out["block_number"] == 19234567
    assert out["tx_from"] == "0x1111111111111111111111111111111111111111"
    assert out["tx_to"] == "0xdac17f958d2ee523a2206206994597c13d831ec7"


def test_parse_gas_fee_arithmetic():
    out = cashflow_tx_fetch.parse_goldrush(USDT_TRANSFER_FIXTURE, "ETHEREUM")
    # 65000 * 20_000_000_000 = 1.3e15 wei = 0.0013 ETH
    assert out["gas_fee"] == "0.0013"


# ── §4: Native transfer + multi-transfer ─────────────────────────

NATIVE_ETH_FIXTURE = {
    "data": {
        "items": [{
            "block_signed_at": "2026-05-22T15:00:00Z",
            "block_height": 19234600,
            "tx_hash": "0x" + "b" * 64,
            "from_address": "0xaaaa000000000000000000000000000000000000",
            "to_address": "0xbbbb000000000000000000000000000000000000",
            "value": "500000000000000000",  # 0.5 ETH
            "gas_spent": 21000,
            "gas_price": 10_000_000_000,
            "log_events": [],
        }],
    },
}


def test_parse_native_transfer_synthesized_when_no_logs():
    out = cashflow_tx_fetch.parse_goldrush(NATIVE_ETH_FIXTURE, "ETHEREUM")
    assert out["transfers"] == [{
        "asset": "ETH",
        "amount": "0.500000000000000000",
        "from": "0xaaaa000000000000000000000000000000000000",
        "to": "0xbbbb000000000000000000000000000000000000",
        "decimals": 18,
        "contract_address": None,
    }]


def test_parse_native_transfer_uses_chain_native_asset():
    out = cashflow_tx_fetch.parse_goldrush(NATIVE_ETH_FIXTURE, "BINANCE SMART CHAIN")
    assert out["transfers"][0]["asset"] == "BNB"


# Two-transfer fixture: a USDC withdraw that also moves a small fee token.
MULTI_TRANSFER_FIXTURE = {
    "data": {
        "items": [{
            "block_signed_at": "2026-05-22T16:00:00Z",
            "block_height": 19234700,
            "tx_hash": "0x" + "c" * 64,
            "from_address": "0xcccc000000000000000000000000000000000000",
            "to_address": "0xdddd000000000000000000000000000000000000",
            "value": "0",
            "gas_spent": 120000,
            "gas_price": 25_000_000_000,
            "log_events": [
                {
                    "sender_contract_decimals": 6,
                    "sender_contract_ticker_symbol": "USDC",
                    "sender_address": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
                    "decoded": {
                        "name": "Transfer",
                        "signature": (_ERC20_SIG := "Transfer(indexed address from, indexed address to, uint256 value)"),
                        "params": [
                            {"name": "from", "type": "address", "value": "0xcccc000000000000000000000000000000000000"},
                            {"name": "to", "type": "address", "value": "0xdddd000000000000000000000000000000000000"},
                            {"name": "value", "type": "uint256", "value": "1000000000"},  # 1000 USDC
                        ],
                    },
                },
                {
                    "sender_contract_decimals": 18,
                    "sender_contract_ticker_symbol": "FEE",
                    "sender_address": "0xfee0000000000000000000000000000000000000",
                    "decoded": {
                        "name": "Transfer",
                        "signature": _ERC20_SIG,
                        "params": [
                            {"name": "from", "type": "address", "value": "0xcccc000000000000000000000000000000000000"},
                            {"name": "to", "type": "address", "value": "0xfee1111111111111111111111111111111111111"},
                            {"name": "value", "type": "uint256", "value": "5000000000000000000"},  # 5 FEE
                        ],
                    },
                },
            ],
        }],
    },
}


def test_parse_multi_transfer_returns_all_in_order():
    out = cashflow_tx_fetch.parse_goldrush(MULTI_TRANSFER_FIXTURE, "ETHEREUM")
    assert len(out["transfers"]) == 2
    assert out["transfers"][0]["asset"] == "USDC"
    assert out["transfers"][0]["amount"] == "1000.000000"
    assert out["transfers"][1]["asset"] == "FEE"
    assert out["transfers"][1]["amount"] == "5.000000000000000000"


# ── §5: HTTP orchestration ───────────────────────────────────────


def _fake_urlopen_json(body: dict):
    """Build a fake urlopen() return value with .read() yielding the JSON body.

    Returns a BytesIO, which satisfies the context-manager contract the script uses
    via `with urllib.request.urlopen(...) as resp` — BytesIO implements __enter__/__exit__.
    """
    return io.BytesIO(_json.dumps(body).encode("utf-8"))


def test_fetch_tx_happy_path(monkeypatch):
    monkeypatch.setenv("GOLDRUSH_API_KEY", "test-key")
    monkeypatch.setattr(
        cashflow_tx_fetch.urllib.request, "urlopen",
        lambda req, timeout=None: _fake_urlopen_json(USDT_TRANSFER_FIXTURE),
    )
    code, out = cashflow_tx_fetch.fetch_tx({"tx_hash": VALID_HASH, "network": "ETHEREUM"})
    assert code == cashflow_tx_fetch.EXIT_OK
    assert out["ok"] is True
    assert out["transfers"][0]["asset"] == "USDT"
    assert out["gas_fee"] == "0.0013"


def test_fetch_tx_validation_fail_no_http_call(monkeypatch):
    monkeypatch.setenv("GOLDRUSH_API_KEY", "test-key")

    def _boom(*a, **k):
        raise AssertionError("urlopen must not be called on validation failure")
    monkeypatch.setattr(cashflow_tx_fetch.urllib.request, "urlopen", _boom)
    code, out = cashflow_tx_fetch.fetch_tx({"tx_hash": "nope", "network": "ETHEREUM"})
    assert code == cashflow_tx_fetch.EXIT_VALIDATION
    assert out["ok"] is False


def test_fetch_tx_goldrush_404(monkeypatch):
    monkeypatch.setenv("GOLDRUSH_API_KEY", "test-key")

    def _raise_404(req, timeout=None):
        raise HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b""))
    monkeypatch.setattr(cashflow_tx_fetch.urllib.request, "urlopen", _raise_404)
    code, out = cashflow_tx_fetch.fetch_tx({"tx_hash": VALID_HASH, "network": "ETHEREUM"})
    assert code == cashflow_tx_fetch.EXIT_NOT_FOUND
    assert out == {"ok": False, "error": "tx not found", "code": "not_found"}


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_fetch_tx_goldrush_5xx_maps_to_upstream(monkeypatch, status):
    monkeypatch.setenv("GOLDRUSH_API_KEY", "test-key")

    def _raise_5xx(req, timeout=None):
        raise HTTPError(req.full_url, status, "Server Error", {}, io.BytesIO(b""))
    monkeypatch.setattr(cashflow_tx_fetch.urllib.request, "urlopen", _raise_5xx)
    code, out = cashflow_tx_fetch.fetch_tx({"tx_hash": VALID_HASH, "network": "ETHEREUM"})
    assert code == cashflow_tx_fetch.EXIT_UPSTREAM
    assert out["code"] == "upstream"


def test_fetch_tx_network_unreachable_maps_to_upstream(monkeypatch):
    monkeypatch.setenv("GOLDRUSH_API_KEY", "test-key")

    def _urlerror(req, timeout=None):
        raise URLError("DNS lookup failed")
    monkeypatch.setattr(cashflow_tx_fetch.urllib.request, "urlopen", _urlerror)
    code, out = cashflow_tx_fetch.fetch_tx({"tx_hash": VALID_HASH, "network": "ETHEREUM"})
    assert code == cashflow_tx_fetch.EXIT_UPSTREAM
    assert out["code"] == "upstream"


def test_fetch_tx_missing_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("GOLDRUSH_API_KEY", raising=False)
    monkeypatch.setattr(cashflow_tx_fetch, "_ENV_FILE", tmp_path / "nope.env")
    code, out = cashflow_tx_fetch.fetch_tx({"tx_hash": VALID_HASH, "network": "ETHEREUM"})
    assert code == cashflow_tx_fetch.EXIT_MISCONFIG


def test_fetch_tx_no_transfers_and_zero_value(monkeypatch):
    monkeypatch.setenv("GOLDRUSH_API_KEY", "test-key")
    empty = {"data": {"items": [{
        "block_signed_at": "2026-05-22T17:00:00Z", "block_height": 1, "tx_hash": VALID_HASH,
        "from_address": "0x0", "to_address": "0x1",
        "value": "0", "gas_spent": 21000, "gas_price": 1, "log_events": [],
    }]}}
    monkeypatch.setattr(
        cashflow_tx_fetch.urllib.request, "urlopen",
        lambda req, timeout=None: _fake_urlopen_json(empty),
    )
    code, out = cashflow_tx_fetch.fetch_tx({"tx_hash": VALID_HASH, "network": "ETHEREUM"})
    assert code == cashflow_tx_fetch.EXIT_NO_XFERS
    assert out["code"] == "no_transfers"


def test_fetch_tx_empty_items_response_maps_to_not_found(monkeypatch):
    """Covalent returns 200 + data.items=[] for unknown tx on some chains."""
    monkeypatch.setenv("GOLDRUSH_API_KEY", "test-key")
    monkeypatch.setattr(
        cashflow_tx_fetch.urllib.request, "urlopen",
        lambda req, timeout=None: _fake_urlopen_json({"data": {"items": []}}),
    )
    code, out = cashflow_tx_fetch.fetch_tx({"tx_hash": VALID_HASH, "network": "ETHEREUM"})
    assert code == cashflow_tx_fetch.EXIT_NOT_FOUND
    assert out == {"ok": False, "error": "tx not found", "code": "not_found"}


def test_read_api_key_prefers_env_over_dotenv(monkeypatch, tmp_path):
    monkeypatch.setenv("GOLDRUSH_API_KEY", "env-wins")
    fake_env = tmp_path / ".env"
    fake_env.write_text("GOLDRUSH_API_KEY=dotenv-loses\n")
    monkeypatch.setattr(cashflow_tx_fetch, "_ENV_FILE", fake_env)
    assert cashflow_tx_fetch._read_api_key() == "env-wins"


def test_read_api_key_falls_back_to_dotenv(monkeypatch, tmp_path):
    monkeypatch.delenv("GOLDRUSH_API_KEY", raising=False)
    fake_env = tmp_path / ".env"
    fake_env.write_text("# some comment\nUNRELATED=foo\nGOLDRUSH_API_KEY=from-dotenv\nMORE=bar\n")
    monkeypatch.setattr(cashflow_tx_fetch, "_ENV_FILE", fake_env)
    assert cashflow_tx_fetch._read_api_key() == "from-dotenv"


def test_read_api_key_returns_none_when_missing_everywhere(monkeypatch, tmp_path):
    monkeypatch.delenv("GOLDRUSH_API_KEY", raising=False)
    monkeypatch.setattr(cashflow_tx_fetch, "_ENV_FILE", tmp_path / "nope.env")
    assert cashflow_tx_fetch._read_api_key() is None


def test_read_api_key_ignores_commented_line(monkeypatch, tmp_path):
    monkeypatch.delenv("GOLDRUSH_API_KEY", raising=False)
    fake_env = tmp_path / ".env"
    fake_env.write_text("# GOLDRUSH_API_KEY=commented-out\nOTHER=x\n")
    monkeypatch.setattr(cashflow_tx_fetch, "_ENV_FILE", fake_env)
    assert cashflow_tx_fetch._read_api_key() is None


# ── §6: Address resolution against reference_data ────────────────

class _FakeCursor:
    """Returns a different result set per table queried, keyed by table name in the SQL."""

    def __init__(self, by_table):
        self._by_table = by_table
        self._buffer = []

    def execute(self, sql, args):
        for table, rows in self._by_table.items():
            if f" {table} " in sql:
                self._buffer = list(rows)
                return
        self._buffer = []

    def fetchall(self):
        return self._buffer

    def close(self):
        pass


class _FakeConn:
    def __init__(self, by_table):
        self._by_table = by_table

    def cursor(self):
        return _FakeCursor(self._by_table)

    def close(self):
        pass


def _install_fake_pymysql(monkeypatch, by_table):
    """Inject a fake pymysql module so resolve_addresses runs without a real DB."""
    import types
    fake = types.ModuleType("pymysql")
    fake.connect = lambda **kw: _FakeConn(by_table)
    monkeypatch.setitem(sys.modules, "pymysql", fake)


def test_resolve_addresses_returns_empty_when_no_creds(monkeypatch):
    monkeypatch.setattr(cashflow_tx_fetch, "_load_refdata_creds", lambda: None)
    assert cashflow_tx_fetch.resolve_addresses(["0xabc"], "ETHEREUM") == {}


def test_resolve_addresses_returns_empty_when_no_addresses(monkeypatch):
    monkeypatch.setattr(cashflow_tx_fetch, "_load_refdata_creds",
                        lambda: {"host": "h", "username": "u", "password": "p"})
    assert cashflow_tx_fetch.resolve_addresses([], "ETHEREUM") == {}


def test_resolve_addresses_hits_counterparty(monkeypatch):
    monkeypatch.setattr(cashflow_tx_fetch, "_load_refdata_creds",
                        lambda: {"host": "h", "username": "u", "password": "p"})
    _install_fake_pymysql(monkeypatch, {
        "counterparty_settlement_crypto": [
            ("0xaaaa000000000000000000000000000000000001", "HASHFLOW FOUNDATION", "Hashflow Monthly Fees"),
        ],
        "account_wallet_deposit": [],
        "account_exchange_deposit": [],
    })
    out = cashflow_tx_fetch.resolve_addresses(
        ["0xAAaa000000000000000000000000000000000001", "0xnomatch00000000000000000000000000000002"],
        "ETHEREUM",
    )
    assert out == {
        "0xaaaa000000000000000000000000000000000001": {
            "kind": "counterparty",
            "owner": "HASHFLOW FOUNDATION",
            "label": "Hashflow Monthly Fees",
        },
    }


def test_resolve_addresses_priority_counterparty_over_wallet(monkeypatch):
    """If an address appears in BOTH tables, the counterparty hit wins (table priority order)."""
    monkeypatch.setattr(cashflow_tx_fetch, "_load_refdata_creds",
                        lambda: {"host": "h", "username": "u", "password": "p"})
    same_addr = "0xcccc000000000000000000000000000000000003"
    _install_fake_pymysql(monkeypatch, {
        "counterparty_settlement_crypto": [(same_addr, "CPARTY", "cp-label")],
        "account_wallet_deposit": [(same_addr, "WALLET", "wallet-label")],
        "account_exchange_deposit": [],
    })
    out = cashflow_tx_fetch.resolve_addresses([same_addr], "ETHEREUM")
    assert out[same_addr]["kind"] == "counterparty"
    assert out[same_addr]["owner"] == "CPARTY"


def test_resolve_addresses_swallows_db_errors(monkeypatch):
    """Resolution is best-effort enrichment — a DB error must not kill the fetch."""
    monkeypatch.setattr(cashflow_tx_fetch, "_load_refdata_creds",
                        lambda: {"host": "h", "username": "u", "password": "p"})
    import types
    bad = types.ModuleType("pymysql")

    def _boom(**kw):
        raise RuntimeError("connection refused")
    bad.connect = _boom
    monkeypatch.setitem(sys.modules, "pymysql", bad)
    assert cashflow_tx_fetch.resolve_addresses(["0xabc"], "ETHEREUM") == {}


def test_fetch_tx_attaches_resolutions_to_response(monkeypatch):
    monkeypatch.setenv("GOLDRUSH_API_KEY", "test-key")
    monkeypatch.setattr(
        cashflow_tx_fetch.urllib.request, "urlopen",
        lambda req, timeout=None: _fake_urlopen_json(USDT_TRANSFER_FIXTURE),
    )
    monkeypatch.setattr(cashflow_tx_fetch, "_load_refdata_creds",
                        lambda: {"host": "h", "username": "u", "password": "p"})
    _install_fake_pymysql(monkeypatch, {
        "counterparty_settlement_crypto": [
            ("0x2222222222222222222222222222222222222222", "SOME COUNTERPARTY", "label-1"),
        ],
        "account_wallet_deposit": [],
        "account_exchange_deposit": [],
    })
    code, out = cashflow_tx_fetch.fetch_tx({"tx_hash": VALID_HASH, "network": "ETHEREUM"})
    assert code == cashflow_tx_fetch.EXIT_OK
    assert "resolutions" in out
    assert out["resolutions"]["0x2222222222222222222222222222222222222222"]["owner"] == "SOME COUNTERPARTY"


def test_fetch_tx_sends_explicit_user_agent(monkeypatch):
    """Goldrush's WAF 403s requests with the default Python-urllib UA — we must override."""
    monkeypatch.setenv("GOLDRUSH_API_KEY", "test-key")
    captured = {}

    def _capture(req, timeout=None):
        # Request.headers normalizes header names to Capitalized-Form
        captured["user_agent"] = req.headers.get("User-agent")
        captured["authorization"] = req.headers.get("Authorization")
        return _fake_urlopen_json(USDT_TRANSFER_FIXTURE)

    monkeypatch.setattr(cashflow_tx_fetch.urllib.request, "urlopen", _capture)
    cashflow_tx_fetch.fetch_tx({"tx_hash": VALID_HASH, "network": "ETHEREUM"})
    assert captured["user_agent"], "User-Agent must be set to avoid Goldrush WAF 403"
    assert "Python-urllib" not in captured["user_agent"]
    assert captured["authorization"] == "Bearer test-key"
