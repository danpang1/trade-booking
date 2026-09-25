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
    # draft_insert relies on (cur, payload) -> dict, same as cashflow_insert.
    import inspect
    params = list(inspect.signature(spot_insert._insert_one).parameters)
    assert params == ["cur", "payload"]


def test_draft_insert_routes_spot_and_cashflow():
    """The trade row is created at BOOKING time now, not on approval, so the
    inserter table lives on draft_insert. draft_approve only moves the row."""
    import draft_insert
    assert set(draft_insert._INSERTERS) == {"CASHFLOW", "SPOT"}
    assert draft_insert._INSERTERS["SPOT"] is spot_insert._insert_one


def test_draft_approve_no_longer_inserts():
    """Approval must AMEND the existing row. If it regained an inserter table
    it would create a second trade for the same draft."""
    import draft_approve
    assert not hasattr(draft_approve, "_INSERTERS")


def test_draft_link_covers_both_categories():
    import draft_trade_link
    assert draft_trade_link.category_table("SPOT")[0] == "trades_spot"
    assert draft_trade_link.category_table("CASHFLOW")[0] == "trades_cashflow"
    assert draft_trade_link.category_table("LOAN") is None


def test_approval_keeps_the_claude_prefix():
    """A trade booked through Colossus stays `claude:<user>` for life.

    Approval used to strip the prefix so a bot-booked trade read like a
    form-booked one. That hid how the trade got there: the blotter should show
    at a glance which trades came in through the bot and who asked for them,
    and the approver is recorded separately in updated_by.
    """
    src = (Path(__file__).resolve().parents[1] / "scripts" / "draft_approve.py").read_text(
        encoding="utf-8"
    )
    assert 'uid[len("claude:"):]' not in src
    assert "claude:" in src, "the decision to keep the prefix should stay documented"


def test_approval_does_not_reassign_the_author():
    """amend_status carries user_id forward from the live row. Passing a
    user_id here would let the approver's payload restate the author."""
    src = (Path(__file__).resolve().parents[1] / "scripts" / "draft_approve.py").read_text(
        encoding="utf-8"
    )
    start = src.index("draft_trade_link.amend_status(")
    # the call ends at the first line that is just a closing paren
    lines = src[start:].splitlines()
    call = []
    for ln in lines:
        call.append(ln)
        if ln.strip() == ")":
            break
    approve_call = "\n".join(call)
    assert "user_id=" not in approve_call, approve_call
    assert "updated_by=acting" in approve_call
