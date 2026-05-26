"""Pure-logic unit tests for draft_db. No DB connection required."""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pytest  # noqa: E402
import draft_db  # noqa: E402


# ── Category validation ─────────────────────────────────────────────

def test_validate_category_accepts_cashflow():
    assert draft_db.validate_category("CASHFLOW") == "CASHFLOW"


def test_validate_category_accepts_spot():
    # SPOT is allowed at the DB level; Plan 1a only routes CASHFLOW.
    assert draft_db.validate_category("SPOT") == "SPOT"


@pytest.mark.parametrize("bad", ["cashflow", "", None, "OTHER", 123])
def test_validate_category_rejects(bad):
    with pytest.raises(draft_db.ValidationError):
        draft_db.validate_category(bad)


# ── client_request_id validation ────────────────────────────────────

def test_validate_uuid_accepts_canonical():
    s = "11111111-2222-3333-4444-555555555555"
    assert draft_db.validate_uuid(s) == s


def test_validate_uuid_accepts_generated():
    s = str(uuid.uuid4())
    assert draft_db.validate_uuid(s) == s


@pytest.mark.parametrize("bad", ["", None, "not-a-uuid", "12345", 42])
def test_validate_uuid_rejects(bad):
    with pytest.raises(draft_db.ValidationError):
        draft_db.validate_uuid(bad)


# ── Status set ──────────────────────────────────────────────────────

def test_statuses_constant_is_complete():
    assert draft_db.STATUSES == ("PENDING_REVIEW", "APPROVED", "REJECTED")


# ── Payload shape gate (calls cashflow_db.validate_payload) ─────────

def test_validate_payload_for_category_cashflow_passes_through():
    """For CASHFLOW, draft_db delegates to cashflow_db.validate_payload(mode='insert').
    A complete CASHFLOW payload should not raise.
    """
    # Use real UAT refdata values — server-side validation now joins
    # against public/refdata/*.json + public/tokens.json.
    payload = {
        "cashflow_type": "OTHER INCOME",
        "direction": "INCOMING",
        "entity": "TOKKA LABS PTE LTD",
        "portfolio_id": 8888,
        "portfolio_name": "TOKKA LABS - TREASURY",
        "counterparty": "BEBOP LTD",
        "account": "TK818@BINANCE",
        "account_type": "EXCHANGE",
        "asset": "USDC",
        "amount": "1.00",
        "trade_date": "2026-05-15T12:00:00+00:00",
        "value_date": "2026-05-15T12:00:00+00:00",
        "user_id": "test",
        "status": "PENDING",
    }
    draft_db.validate_payload_for_category("CASHFLOW", payload)  # no raise


def test_validate_payload_for_category_cashflow_unknown_counterparty_raises():
    """Server checks counterparty against public/refdata/counterparties.json
    so a non-refdata name like 'CONTRA' or 'OPENAI' can't slip through.
    Mirrors the form's counterparty dropdown which is refdata-driven."""
    payload = {
        "cashflow_type": "OPEX",
        "direction": "OUTGOING",
        "entity": "TOKKA LABS PTE LTD",
        "portfolio_id": 8888,
        "portfolio_name": "TOKKA LABS - TREASURY",
        "counterparty": "CONTRA",  # not in 174-item refdata
        "account": "TK818@BINANCE",
        "asset": "USDC",
        "amount": "-1",
        "trade_date": "2026-05-26T12:00:00+00:00",
        "value_date": "2026-05-26T12:00:00+00:00",
        "user_id": "claude:danny.pang",
        "status": "PENDING",
    }
    with pytest.raises(draft_db.ValidationError, match="counterparty"):
        draft_db.validate_payload_for_category("CASHFLOW", payload)


def test_validate_payload_for_category_cashflow_unknown_network_raises():
    """Network is uppercase per src/data/networks.js. Lowercase 'Ethereum'
    must fail — bites users who type case-insensitively."""
    payload = {
        "cashflow_type": "OPEX",
        "direction": "OUTGOING",
        "entity": "TOKKA LABS PTE LTD",
        "portfolio_id": 8888,
        "portfolio_name": "TOKKA LABS - TREASURY",
        "counterparty": "BEBOP LTD",
        "account": "TK818@BINANCE",
        "asset": "USDC",
        "amount": "-1",
        "network": "Ethereum",  # wrong case, real value is "ETHEREUM"
        "trade_date": "2026-05-26T12:00:00+00:00",
        "value_date": "2026-05-26T12:00:00+00:00",
        "user_id": "claude:danny.pang",
        "status": "PENDING",
    }
    with pytest.raises(draft_db.ValidationError, match="network"):
        draft_db.validate_payload_for_category("CASHFLOW", payload)


def test_validate_payload_for_category_cashflow_unknown_type_raises():
    """The server enforces the same 11-item cashflow_type enum that the
    form's dropdown uses, so a non-standard type like 'TRADING FEES' gets
    a 400 instead of silently passing through to a draft with a blank
    dropdown for the human reviewer."""
    payload = {
        "cashflow_type": "TRADING FEES",  # not in the 11-item list
        "direction": "OUTGOING",
        "entity": "TOKKA LABS PTE LTD",
        "portfolio_id": 8888,
        "portfolio_name": "TOKKA LABS - TREASURY",
        "counterparty": "BEBOP LTD",
        "account": "TK818@BINANCE",
        "asset": "USDC",
        "amount": "-38.8",
        "trade_date": "2026-05-26T12:00:00+00:00",
        "value_date": "2026-05-26T12:00:00+00:00",
        "user_id": "claude:danny.pang",
        "status": "PENDING",
    }
    with pytest.raises(draft_db.ValidationError, match="cashflow_type"):
        draft_db.validate_payload_for_category("CASHFLOW", payload)


def test_validate_payload_for_category_cashflow_blank_account_raises():
    """The form requires account_name; the server now mirrors that.
    Before the cashflow_db.REQUIRED_FIELDS_INSERT change, a draft
    submission with blank account silently approved into a trades_cashflow
    row with NULL account (e.g. MCF00000034). Regression test."""
    payload = {
        "cashflow_type": "OPEX",
        "direction": "OUTGOING",
        "entity": "TOKKA LABS PTE LTD",
        "portfolio_id": 8888,
        "portfolio_name": "TOKKA LABS - TREASURY",
        "counterparty": "BEBOP LTD",
        # "account": missing on purpose
        "asset": "USDC",
        "amount": "-88",
        "trade_date": "2026-05-26T12:00:00+00:00",
        "value_date": "2026-05-26T12:00:00+00:00",
        "user_id": "claude:danny.pang",
        "status": "PENDING",
    }
    with pytest.raises(draft_db.ValidationError, match="account"):
        draft_db.validate_payload_for_category("CASHFLOW", payload)


def test_validate_payload_for_category_cashflow_zero_amount_raises():
    """Mirror the form's 'Notional amount must be > 0' rule."""
    payload = {
        "cashflow_type": "OPEX",
        "direction": "OUTGOING",
        "entity": "TOKKA LABS PTE LTD",
        "portfolio_id": 8888,
        "portfolio_name": "TOKKA LABS - TREASURY",
        "counterparty": "BEBOP LTD",
        "account": "TK818@BINANCE",
        "asset": "USDC",
        "amount": "0",
        "trade_date": "2026-05-26T12:00:00+00:00",
        "value_date": "2026-05-26T12:00:00+00:00",
        "user_id": "claude:danny.pang",
        "status": "PENDING",
    }
    with pytest.raises(draft_db.ValidationError, match="non-zero"):
        draft_db.validate_payload_for_category("CASHFLOW", payload)


def test_validate_payload_for_category_cashflow_missing_field_raises():
    bad = {"cashflow_type": "FUNDING IN"}  # missing many required
    with pytest.raises(draft_db.ValidationError):
        draft_db.validate_payload_for_category("CASHFLOW", bad)


def test_validate_payload_for_category_spot_not_implemented_in_phase_1a():
    """Plan 1a is CASHFLOW-only. SPOT is accepted at DB level but the
    endpoint must reject it cleanly. validate_payload_for_category
    raises a clear error for SPOT until Phase 2 wires spot_db."""
    with pytest.raises(draft_db.ValidationError, match="SPOT"):
        draft_db.validate_payload_for_category("SPOT", {})


# ── row_to_public ───────────────────────────────────────────────────

def test_row_to_public_omits_internal_fields_and_isoformats_dates():
    """row_to_public maps a SELECT-* row to the API JSON payload.
    Internal-only columns aren't omitted (drafts have nothing secret),
    but datetimes must be JSON-safe (ISO 8601 strings)."""
    import datetime as dt

    class FakeCol:
        def __init__(self, name):
            self.name = name

    class FakeCur:
        description = [FakeCol(n) for n in (
            "id", "category", "payload", "status", "batch_id",
            "client_request_id", "created_by", "created_at",
            "updated_at", "approved_at", "approved_by",
            "approved_deal_ref", "rejected_at", "rejected_by",
            "rejection_reason",
        )]

    row = (
        42, "CASHFLOW", {"a": 1}, "PENDING_REVIEW", None,
        "00000000-0000-0000-0000-000000000001", "alice",
        dt.datetime(2026, 5, 25, 10, 0, 0, tzinfo=dt.timezone.utc),
        dt.datetime(2026, 5, 25, 10, 0, 0, tzinfo=dt.timezone.utc),
        None, None, None, None, None, None,
    )
    out = draft_db.row_to_public(FakeCur(), row)
    assert out["id"] == 42
    assert out["category"] == "CASHFLOW"
    assert out["payload"] == {"a": 1}
    assert out["status"] == "PENDING_REVIEW"
    assert out["created_by"] == "alice"
    assert out["created_at"].startswith("2026-05-25T10:00:00")
    assert out["approved_at"] is None
