"""Tests for scripts/account_id_resolve.py.

The property that matters most: this must NEVER raise. It runs inside the
booking path, and a trade failing because a mirror-id lookup timed out would
be a worse outcome than a NULL column.
"""
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import account_id_resolve as air  # noqa: E402


class FakeConn:
    def __init__(self, result=None, raises=None):
        self.result = result
        self.raises = raises

    def __enter__(self):
        if self.raises:
            raise self.raises
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return object()


def _stub_t2x(monkeypatch, *, result=None, connect_raises=None,
              resolve_raises=None):
    """Install a fake t2x_mysql module for the late import inside resolve()."""
    import types
    mod = types.ModuleType("t2x_mysql")

    def connect():
        if connect_raises:
            raise connect_raises
        return FakeConn()

    def resolve_account_id(cur, name, at, suffix):
        if resolve_raises:
            raise resolve_raises
        return result

    mod.connect = connect
    mod.resolve_account_id = resolve_account_id
    monkeypatch.setitem(sys.modules, "t2x_mysql", mod)


# ── the happy path ────────────────────────────────────────────────────

def test_an_exchange_account_resolves(monkeypatch):
    _stub_t2x(monkeypatch, result="218001")
    assert air.resolve("ECT001@BINANCE", "EXCHANGE", "spot") == "218001"


def test_account_type_is_mapped_to_the_gateway_table_name(monkeypatch):
    seen = {}
    import types
    mod = types.ModuleType("t2x_mysql")
    mod.connect = lambda: FakeConn()

    def cap(cur, name, at, suffix):
        seen["at"] = at
        return "1001"

    mod.resolve_account_id = cap
    monkeypatch.setitem(sys.modules, "t2x_mysql", mod)
    air.resolve("W1", "WALLET", "ethereum")
    assert seen["at"] == "wallet"


# ── fail safe: every failure is a None, never an exception ────────────

def test_no_account_is_none(monkeypatch):
    _stub_t2x(monkeypatch, result="218001")
    assert air.resolve("", "EXCHANGE", "spot") is None
    assert air.resolve(None, "EXCHANGE", "spot") is None


def test_a_bank_account_has_no_gateway_id(monkeypatch):
    """BANK is a real account_type on a booking but has no gateway account."""
    _stub_t2x(monkeypatch, result="218001")
    assert air.resolve("B1@DBS", "BANK", None) is None


def test_an_unknown_account_type_is_none(monkeypatch):
    _stub_t2x(monkeypatch, result="218001")
    assert air.resolve("X", "SOMETHING_NEW", "spot") is None


def test_t2x_unreachable_is_none_not_an_exception(monkeypatch):
    _stub_t2x(monkeypatch, connect_raises=OSError("connection refused"))
    assert air.resolve("ECT001@BINANCE", "EXCHANGE", "spot") is None


def test_a_resolver_error_is_none_not_an_exception(monkeypatch):
    _stub_t2x(monkeypatch, resolve_raises=ValueError("bad row"))
    assert air.resolve("ECT001@BINANCE", "EXCHANGE", "spot") is None


def test_a_missing_driver_is_none_not_an_exception(monkeypatch):
    """The late import is inside the try for exactly this reason."""
    monkeypatch.setitem(sys.modules, "t2x_mysql", None)
    assert air.resolve("ECT001@BINANCE", "EXCHANGE", "spot") is None


def test_an_unmapped_product_is_none(monkeypatch):
    """REYA / STARKNET / FUTURES2 / FUTURES3 have no gateway code — the
    resolver returns None and the column stays NULL."""
    _stub_t2x(monkeypatch, result=None)
    assert air.resolve("W1", "WALLET", "REYA") is None


# ── stamping ──────────────────────────────────────────────────────────

def test_stamp_sets_the_field(monkeypatch):
    _stub_t2x(monkeypatch, result="218001")
    p = {"account": "ECT001@BINANCE", "account_type": "EXCHANGE", "product": "spot"}
    air.stamp(p)
    assert p["account_id"] == "218001"


def test_stamp_overwrites_anything_the_client_sent(monkeypatch):
    """The row's account and product are the truth, not a client-supplied id."""
    _stub_t2x(monkeypatch, result="218001")
    p = {"account": "ECT001@BINANCE", "account_type": "EXCHANGE",
         "product": "spot", "account_id": "999999"}
    air.stamp(p)
    assert p["account_id"] == "218001"


def test_stamp_sets_none_rather_than_omitting_the_key(monkeypatch):
    """An explicit None writes NULL; a missing key would fall to whatever
    payload_to_columns defaults to."""
    _stub_t2x(monkeypatch, result=None)
    p = {"account": "W1", "account_type": "WALLET", "product": "REYA"}
    air.stamp(p)
    assert "account_id" in p and p["account_id"] is None


def test_stamp_all_covers_every_leg_of_a_transfer(monkeypatch):
    _stub_t2x(monkeypatch, result="218001")
    legs = [
        {"account": "A", "account_type": "EXCHANGE", "product": "spot"},
        {"account": "B", "account_type": "EXCHANGE", "product": "spot"},
    ]
    air.stamp_all(legs)
    assert [leg["account_id"] for leg in legs] == ["218001", "218001"]


def test_stamp_all_accepts_a_single_dict(monkeypatch):
    _stub_t2x(monkeypatch, result="218001")
    p = {"account": "A", "account_type": "EXCHANGE", "product": "spot"}
    air.stamp_all(p)
    assert p["account_id"] == "218001"


def test_stamp_ignores_a_non_dict_leg(monkeypatch):
    _stub_t2x(monkeypatch, result="218001")
    air.stamp("not a dict")  # must not raise


# ── reverse: id -> account + product ──────────────────────────────────
# This is the one that can silently attach a WRONG product to a whole
# batch, so the ambiguous codes and the round-trip guard get the attention.

class FakeCur:
    """Minimal cursor over an in-memory account table."""

    def __init__(self, exchange=None, wallet=None, broker=None):
        self.exchange = exchange or {}
        self.wallet = wallet or {}
        self.broker = broker or {}
        self._row = None

    def execute(self, sql, args=None):
        rid = args[0] if args else None
        if "account_exchange" in sql:
            hit = self.exchange.get(rid)
            self._row = (hit[0], hit[1]) if hit else None
        elif "account_wallet" in sql:
            hit = self.wallet.get(rid)
            self._row = (hit[0], hit[1]) if hit else None
        elif "account_broker" in sql:
            hit = self.broker.get(rid)
            self._row = (hit,) if hit else None
        else:
            self._row = None

    def fetchone(self):
        return self._row


class FakeRevConn:
    def __init__(self, cur):
        self._cur = cur

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return self._cur


def _stub_reverse(monkeypatch, cur):
    import types
    import gateway_rule
    mod = types.ModuleType("t2x_mysql")
    mod.connect = lambda: FakeRevConn(cur)
    mod._rule_codes = lambda c: gateway_rule.hardcoded_codes()
    monkeypatch.setitem(sys.modules, "t2x_mysql", mod)


def test_reverse_resolves_an_exchange_id(monkeypatch):
    _stub_reverse(monkeypatch, FakeCur(exchange={3: ("MOON@BINANCE", "SPOT,USDT_FUTURE")}))
    assert air.reverse("3001") == {
        "account": "MOON@BINANCE", "account_type": "EXCHANGE", "product": "SPOT",
    }


def test_reverse_picks_the_right_half_of_an_ambiguous_code(monkeypatch):
    """001 is both `spot` and `trading`. The account lists only TRADING, so
    that is the answer — this is what makes the reverse a function."""
    _stub_reverse(monkeypatch, FakeCur(exchange={9: ("BROK@X", "TRADING")}))
    assert air.reverse("9001")["product"] == "TRADING"


def test_reverse_uses_the_accounts_own_spelling(monkeypatch):
    _stub_reverse(monkeypatch, FakeCur(exchange={3: ("A@B", "usdt_future")}))
    assert air.reverse("3002")["product"] == "usdt_future"


def test_reverse_rejects_a_product_the_account_does_not_offer(monkeypatch):
    """id says ALPHA (008) but the account only has SPOT — refuse rather
    than attach a product that account cannot trade."""
    _stub_reverse(monkeypatch, FakeCur(exchange={3: ("A@B", "SPOT")}))
    assert air.reverse("3008") is None


def test_reverse_resolves_a_wallet_chain(monkeypatch):
    import json
    deposits = json.dumps([{"chain": "ETHEREUM"}, {"chain": "SOLANA"}])
    _stub_reverse(monkeypatch, FakeCur(wallet={7: ("W1", deposits)}))
    got = air.reverse("7501")
    assert got == {"account": "W1", "account_type": "WALLET", "product": "ETHEREUM"}


def test_reverse_handles_an_aliased_chain(monkeypatch):
    import json
    deposits = json.dumps([{"chain": "BINANCE SMART CHAIN"}])
    _stub_reverse(monkeypatch, FakeCur(wallet={7: ("W1", deposits)}))
    assert air.reverse("7502")["product"] == "BINANCE SMART CHAIN"


def test_reverse_gives_a_broker_no_product(monkeypatch):
    _stub_reverse(monkeypatch, FakeCur(broker={4: "BRK1"}))
    assert air.reverse("4201") == {
        "account": "BRK1", "account_type": "BROKER", "product": None,
    }


def test_reverse_rejects_an_unknown_row_id(monkeypatch):
    _stub_reverse(monkeypatch, FakeCur(exchange={3: ("A@B", "SPOT")}))
    assert air.reverse("999001") is None


def test_reverse_rejects_an_unknown_code(monkeypatch):
    _stub_reverse(monkeypatch, FakeCur(exchange={3: ("A@B", "SPOT")}))
    assert air.reverse("3777") is None


def test_reverse_rejects_malformed_input(monkeypatch):
    _stub_reverse(monkeypatch, FakeCur())
    for bad in ("", None, "abc", "3", "001", "3001x", "  "):
        assert air.reverse(bad) is None


def test_reverse_never_raises_when_t2x_is_down(monkeypatch):
    import types
    mod = types.ModuleType("t2x_mysql")

    def boom():
        raise OSError("connection refused")

    mod.connect = boom
    mod._rule_codes = lambda c: {}
    monkeypatch.setitem(sys.modules, "t2x_mysql", mod)
    assert air.reverse("3001") is None


def test_reverse_round_trips_through_resolve(monkeypatch):
    """Whatever comes back must rebuild the id it came from — the guard that
    keeps this safe if a colliding account ever appears."""
    import gateway_rule
    _stub_reverse(monkeypatch, FakeCur(exchange={3: ("A@B", "SPOT,USDT_FUTURE")}))
    for wanted in ("3001", "3002"):
        got = air.reverse(wanted)
        back = gateway_rule.generate_trading_account_id(
            3, got["account_type"].lower(), got["product"]
        )
        assert str(back) == wanted
