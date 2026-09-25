"""Unit tests for t2x_mysql.resolve_account_id (scripts/t2x_mysql.py).

Uses a fake cursor (no MySQL) to exercise the type dispatch, product/chain
validation, alias handling and account-type inference around the gateway rule.
The rule arithmetic itself is covered by test_gateway_rule.py.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import gateway_rule as gr  # noqa: E402
import t2x_mysql as t  # noqa: E402

# gateway_rule rows the fake DB serves — the hardcoded codes, as (accountType,
# suffix, code), so the DB-driven path yields the same ids as the port.
_RULE_ROWS = [
    (k.split("-", 1)[0], k.split("-", 1)[1], v)
    for k, v in gr.hardcoded_codes().items()
]


@pytest.fixture(autouse=True)
def _reset_rule_cache():
    """resolve_account_id caches the rule per process; reset between tests."""
    t._RULE_CODES = None
    yield
    t._RULE_CODES = None


# In-memory reference_data, keyed by table then account name.
_EXCHANGE = {
    "ECT001@BINANCE": (3, "spot,usdt_future"),
    "test0011@BITSTAMP": (62, "spot"),
    "NOPROD@X": (70, None),  # products column NULL -> no membership check
}
_BROKER = {"IB-MAIN@IBKR": (5,)}
_WALLET = {
    "MM@ETH": (10, '[{"chain":"ethereum"},{"chain":"solana"},{"chain":"BINANCE SMART CHAIN"}]'),
    "PH@SOL": (11, '[{"chain":"solana"}]'),
}


class FakeCursor:
    """Minimal DB-API cursor: routes the resolver's SELECTs to the fixtures.

    `serve_rule` toggles whether the gateway_rule query returns rows (DB source)
    or raises (table absent -> resolver falls back to the hardcoded port).
    """

    def __init__(self, serve_rule=True):
        self._row = None
        self._rows = None
        self._serve_rule = serve_rule

    def execute(self, sql, params=None):
        if "FROM gateway_rule" in sql:
            if not self._serve_rule:
                raise Exception("Table 'reference_data.gateway_rule' doesn't exist")
            self._rows = _RULE_ROWS
            self._row = None
            return
        name = params[0]
        if "FROM account_exchange" in sql:
            self._row = _EXCHANGE.get(name)
        elif "FROM account_broker" in sql:
            self._row = _BROKER.get(name)
        elif "FROM account_wallet" in sql:
            self._row = _WALLET.get(name)
        else:  # pragma: no cover - guards a typo'd query
            raise AssertionError(f"unexpected query: {sql}")

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows or []


def r(name, account_type=None, suffix=None):
    return t.resolve_account_id(FakeCursor(), name, account_type, suffix)


def test_exchange_product_resolution():
    assert r("ECT001@BINANCE", "exchange", "spot") == "3001"
    assert r("ECT001@BINANCE", "exchange", "usdt_future") == "3002"
    assert r("test0011@BITSTAMP", "exchange", "spot") == "62001"


def test_exchange_rejects_product_not_in_account():
    # coin_future is a valid rule key but not in this account's products
    assert r("ECT001@BINANCE", "exchange", "coin_future") is None


def test_exchange_missing_product_is_none():
    assert r("ECT001@BINANCE", "exchange", None) is None
    assert r("ECT001@BINANCE", "exchange", "") is None


def test_exchange_null_products_skips_membership_but_rule_still_applies():
    # products column NULL -> membership not enforced; rule maps spot -> 001
    assert r("NOPROD@X", "exchange", "spot") == "70001"
    # ...but an unmapped product still yields None via the rule
    assert r("NOPROD@X", "exchange", "bogus") is None


def test_broker_is_always_trading_201():
    assert r("IB-MAIN@IBKR", "broker") == "5201"
    assert r("IB-MAIN@IBKR", "broker", "ignored") == "5201"


def test_wallet_chain_resolution_and_alias():
    assert r("MM@ETH", "wallet", "ethereum") == "10501"
    assert r("MM@ETH", "wallet", "solana") == "10701"
    assert r("MM@ETH", "wallet", "BINANCE SMART CHAIN") == "10502"  # alias -> bsc
    assert r("PH@SOL", "wallet", "solana") == "11701"


def test_wallet_rejects_chain_not_a_deposit():
    assert r("MM@ETH", "wallet", "arbitrum") is None


def test_type_inference_when_account_type_omitted():
    assert r("ECT001@BINANCE", None, "spot") == "3001"     # inferred exchange
    assert r("IB-MAIN@IBKR", None, None) == "5201"          # inferred broker
    assert r("MM@ETH", None, "ethereum") == "10501"         # inferred wallet


def test_unknown_account_is_none():
    assert r("NOPE@NOWHERE", "exchange", "spot") is None
    assert r("", "exchange", "spot") is None
    assert r(None, "exchange", "spot") is None


def test_unknown_account_type_falls_back_to_inference():
    # a venue-type like 'CEX' isn't a gateway category -> infer from tables
    assert r("ECT001@BINANCE", "CEX", "spot") == "3001"


def test_db_gateway_rule_is_source_of_truth():
    # DB maps exchange-spot -> 099; the resolver must honour it over the port's 001
    t._RULE_CODES = None

    class C(FakeCursor):
        def execute(self, sql, params=None):
            if "FROM gateway_rule" in sql:
                self._rows = [("exchange", "spot", "099")]
                self._row = None
                return
            super().execute(sql, params)

    assert t.resolve_account_id(C(), "ECT001@BINANCE", "exchange", "spot") == "3099"


def test_falls_back_to_hardcoded_when_gateway_rule_absent():
    # gateway_rule table missing -> load returns None -> hardcoded port used
    t._RULE_CODES = None
    cur = FakeCursor(serve_rule=False)
    assert t.resolve_account_id(cur, "ECT001@BINANCE", "exchange", "spot") == "3001"


def test_product_suffixed_account_name_is_stripped():
    # trades_* store "<name>_<PRODUCT>"; the resolver strips it to match the
    # bare account_exchange.name, so either form resolves the same.
    assert r("ECT001@BINANCE_SPOT", "exchange", "spot") == "3001"
    assert r("ECT001@BINANCE_USDT_FUTURE", "exchange", "usdt_future") == "3002"
    # wallet chain suffix (with alias) stripped too
    assert r("MM@ETH_SOLANA", "wallet", "solana") == "10701"
    assert r("MM@ETH_BINANCE SMART CHAIN", "wallet", "BINANCE SMART CHAIN") == "10502"
