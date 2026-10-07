"""Pure-logic tests for the two-draft INTERNAL transfer pair and the transfer
bulk amend request shape. No DB connection required: the cursor is a stub."""
from __future__ import annotations
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pytest  # noqa: E402
import cashflow_db  # noqa: E402
import draft_insert  # noqa: E402
import draft_trade_link  # noqa: E402
import transfer_amend_batch  # noqa: E402
import transfer_db  # noqa: E402


@pytest.fixture(autouse=True)
def _stub_refdata(monkeypatch):
    monkeypatch.setattr(cashflow_db, "_load_accounts_set",
                        lambda: {"TK818@BINANCE", "TK801@BINANCE"})
    monkeypatch.setattr(cashflow_db, "_load_counterparties_set", lambda: {"BEBOP LTD"})
    monkeypatch.setattr(cashflow_db, "_load_assets_set", lambda: {"USDC", "USDT"})


class _Cursor:
    """Records SQL + args; answers fetchone from a queue."""

    def __init__(self, answers=()):
        self.calls = []
        self.answers = list(answers)
        self.description = []

    def execute(self, sql, args=None):
        self.calls.append((" ".join(sql.split()), args))

    def fetchone(self):
        return self.answers.pop(0) if self.answers else None


# ── mirror_request_id ───────────────────────────────────────────────

def test_mirror_request_id_is_a_valid_uuid_distinct_from_the_original():
    crid = str(uuid.uuid4())
    twin = draft_insert.mirror_request_id(crid)
    assert uuid.UUID(twin)
    assert twin != crid


def test_mirror_request_id_is_deterministic_per_request():
    crid = str(uuid.uuid4())
    assert draft_insert.mirror_request_id(crid) == draft_insert.mirror_request_id(crid)
    assert draft_insert.mirror_request_id(crid) != draft_insert.mirror_request_id(str(uuid.uuid4()))


# ── mirror_draft_payload ────────────────────────────────────────────

def _booked_pair():
    leg = {
        "deal_ref": "MTR00000009", "transfer_type": "INTERNAL", "direction": "OUTGOING",
        "source_account_name": "TK818@BINANCE", "source_product": "SPOT", "source_account_id": "3001",
        "dest_account_name": "TK801@BINANCE", "dest_product": "SPOT", "dest_account_id": "3002",
        "asset": "USDC", "amount": "-88", "fee_asset": None, "fee_amount": "0",
        "initiated_datetime": "2026-10-07T07:41:01+00:00", "completed_datetime": "2026-10-07T07:41:01+00:00",
        "network": None, "ext_transfer_id": None, "user_id": "claude:danny.pang", "status": "PENDING",
        "comment": "Settlement", "updated_by": None, "internal_journal": None,
        # aliases row_to_payload adds for Deal Enquiry
        "txn_type": "TRANSFER", "trade_date": "x", "value_date": "y", "account": "a", "counterparty": "b",
        "id": 9, "effective_start": "now", "effective_end": None,
    }
    mirror = dict(leg, deal_ref="MTR00000010", direction="INCOMING", amount="88",
                  source_account_name="TK801@BINANCE", source_account_id="3002",
                  dest_account_name="TK818@BINANCE", dest_account_id="3001", id=10)
    return [leg, mirror]


def test_mirror_draft_payload_none_without_a_mirror():
    assert draft_insert.mirror_draft_payload([_booked_pair()[0]]) is None
    assert draft_insert.mirror_draft_payload([]) is None
    assert draft_insert.mirror_draft_payload(None) is None


def test_mirror_draft_payload_is_the_mirror_leg_columns_only():
    p = draft_insert.mirror_draft_payload(_booked_pair())
    assert p["direction"] == "INCOMING" and p["amount"] == "88"
    assert p["source_account_name"] == "TK801@BINANCE"
    assert p["dest_account_name"] == "TK818@BINANCE"
    assert "deal_ref" not in p
    for alias in ("txn_type", "trade_date", "value_date", "account", "counterparty",
                  "id", "effective_start", "effective_end"):
        assert alias not in p
    assert set(p) == set(transfer_db.DATA_COLUMNS) - {"deal_ref"}


def test_mirror_draft_payload_validates_as_a_transfer_draft():
    # The Approvals page opens it in the form and draft_patch validates it,
    # so it must pass the same insert-mode check as the primary.
    p = draft_insert.mirror_draft_payload(_booked_pair())
    transfer_db.validate_payload(p, mode="insert")


# ── move_sibling_draft ──────────────────────────────────────────────

def test_move_sibling_draft_approves_the_twin_once():
    cur = _Cursor(answers=[(43,)])
    out = draft_trade_link.move_sibling_draft(
        cur, {"_meta": {"mirror_draft_id": 43}}, "APPROVED", "alice")
    assert out == 43
    sql, args = cur.calls[0]
    assert "status = 'APPROVED'" in sql and "status = 'PENDING_REVIEW'" in sql
    assert args == ("alice", 43)


def test_move_sibling_draft_rejects_with_reason():
    cur = _Cursor(answers=[(43,)])
    out = draft_trade_link.move_sibling_draft(
        cur, {"_meta": {"mirror_draft_id": 43}}, "REJECTED", "alice", "typo")
    assert out == 43
    sql, args = cur.calls[0]
    assert "status = 'REJECTED'" in sql
    assert args == ("alice", "typo", 43)


def test_move_sibling_draft_is_a_no_op_without_a_twin():
    cur = _Cursor()
    assert draft_trade_link.move_sibling_draft(cur, {"_meta": {}}, "APPROVED", "a") is None
    assert draft_trade_link.move_sibling_draft(cur, {}, "APPROVED", "a") is None
    assert draft_trade_link.move_sibling_draft(cur, None, "APPROVED", "a") is None
    assert draft_trade_link.move_sibling_draft(
        cur, {"_meta": {"mirror_draft_id": "43"}}, "APPROVED", "a") is None
    assert cur.calls == []


def test_move_sibling_draft_returns_none_when_twin_already_decided():
    cur = _Cursor(answers=[None])
    assert draft_trade_link.move_sibling_draft(
        cur, {"_meta": {"mirror_draft_id": 43}}, "APPROVED", "a") is None


def test_move_sibling_draft_refuses_other_statuses():
    with pytest.raises(draft_trade_link.LinkError):
        draft_trade_link.move_sibling_draft(
            _Cursor(), {"_meta": {"mirror_draft_id": 43}}, "PENDING_REVIEW", "a")


# ── transfer_amend_batch.prepare_rows ───────────────────────────────

def _amend_payload(**over):
    p = {
        "deal_ref": "MTR00000009", "transfer_type": "INTERNAL", "direction": "OUTGOING",
        "source_account_name": "TK818@BINANCE", "source_product": "SPOT",
        "dest_account_name": "TK801@BINANCE", "dest_product": "SPOT",
        "asset": "USDC", "amount": "-88", "initiated_datetime": "2026-10-07T07:41:01+00:00",
        "user_id": "danny.pang", "status": "COMPLETED",
    }
    p.update(over)
    return p


def test_prepare_rows_accepts_a_rows_envelope_and_a_bare_list():
    rows = [_amend_payload(), _amend_payload(deal_ref="MTR00000010", direction="INCOMING", amount="88")]
    assert transfer_amend_batch.prepare_rows({"rows": rows}) == rows
    assert transfer_amend_batch.prepare_rows(rows) == rows


@pytest.mark.parametrize("bad", [{}, {"rows": []}, {"rows": "x"}, [], None])
def test_prepare_rows_rejects_an_empty_request(bad):
    with pytest.raises(transfer_db.ValidationError):
        transfer_amend_batch.prepare_rows(bad)


def test_prepare_rows_names_the_offending_leg():
    rows = [_amend_payload(), _amend_payload(deal_ref="MTR00000010", amount="88")]
    with pytest.raises(transfer_db.ValidationError) as ei:
        transfer_amend_batch.prepare_rows({"rows": rows})
    assert ei.value.deal_ref == "MTR00000010"
    assert "sign" in str(ei.value)


def test_prepare_rows_requires_a_deal_ref_on_every_leg():
    p = _amend_payload()
    del p["deal_ref"]
    with pytest.raises(transfer_db.ValidationError):
        transfer_amend_batch.prepare_rows({"rows": [p]})
