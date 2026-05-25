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
    payload = {
        "cashflow_type": "FUNDING IN",
        "direction": "INCOMING",
        "entity": "TK006",
        "portfolio_id": 8006,
        "portfolio_name": "CDA",
        "counterparty": "Galaxy",
        "asset": "USDC",
        "amount": "1.00",
        "trade_date": "2026-05-15T12:00:00+00:00",
        "value_date": "2026-05-15T12:00:00+00:00",
        "user_id": "test",
        "status": "PENDING",
    }
    draft_db.validate_payload_for_category("CASHFLOW", payload)  # no raise


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
