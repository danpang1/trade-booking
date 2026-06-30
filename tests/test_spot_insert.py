"""Pure-logic tests for the spot_insert refactor + draft_approve routing.

No DB connection: _insert_one is exercised against a fake cursor, and the
approve dispatch table is checked structurally.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pytest  # noqa: E402
import spot_insert  # noqa: E402


class _FakeCol:
    def __init__(self, name):
        self.name = name


class _FakeCursor:
    """Captures the INSERT and returns a canned RETURNING * row."""

    def __init__(self):
        self.executed = None
        # Simulate RETURNING * over a few columns including the DB-generated
        # deal_ref. row_to_payload zips these names against the row tuple.
        self._desc_names = ("deal_ref", "base_asset", "quote_asset", "status")
        self._row = ("MFX00000123", "USDG", "USDC", "PENDING")
        self.description = [_FakeCol(n) for n in self._desc_names]

    def execute(self, sql, vals):
        self.executed = (sql, vals)

    def fetchone(self):
        return self._row


SPOT_PAYLOAD = {
    "direction": "LONG",
    "entity": "TOKKA LABS PTE LTD",
    "portfolio_id": 8041,
    "portfolio_name": "TOKKA LABS - MM - CENTRAL RISK BOOK",
    "base_asset": "USDG",
    "base_amount": "1000000",
    "quote_asset": "USDC",
    "quote_amount": "1000000",
    "price": "1.0",
    "trade_date": "2026-06-30T12:00:00+00:00",
    "value_date": "2026-06-30T12:00:00+00:00",
    "user_id": "danny.pang",
    "status": "PENDING",
}


def test_insert_one_returns_row_and_omits_deal_ref_on_insert():
    cur = _FakeCursor()
    row = spot_insert._insert_one(cur, SPOT_PAYLOAD)
    # Row is the JSON-safe mapping of RETURNING *.
    assert row["deal_ref"] == "MFX00000123"
    assert row["base_asset"] == "USDG"
    assert row["status"] == "PENDING"
    # The INSERT must omit deal_ref (DB default assigns it) and append the
    # SCD2 effective_start/effective_end expressions.
    sql, vals = cur.executed
    assert "INSERT INTO trades_spot" in sql
    assert "deal_ref" not in sql
    assert "NOW(), NULL" in sql
    assert len(vals) == sql.count("%s")


def test_insert_one_signature_matches_cashflow():
    # draft_approve relies on (cur, payload) -> dict, same as cashflow_insert.
    import inspect
    params = list(inspect.signature(spot_insert._insert_one).parameters)
    assert params == ["cur", "payload"]


def test_draft_approve_routes_spot_and_cashflow():
    import draft_approve
    assert set(draft_approve._INSERTERS) == {"CASHFLOW", "SPOT"}
    assert draft_approve._INSERTERS["SPOT"] is spot_insert._insert_one
