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
