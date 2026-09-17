"""Pure-logic unit tests for draft_db. No DB connection required."""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pytest  # noqa: E402
import cashflow_db  # noqa: E402
import draft_db  # noqa: E402


@pytest.fixture(autouse=True)
def _stub_refdata(monkeypatch):
    """Pin refdata so tests don't depend on public/refdata/*.json being present
    inside the Docker test container. The validator silently skips enum checks
    when refdata returns empty; that masked the unknown-counterparty test in CI."""
    monkeypatch.setattr(cashflow_db, "_load_counterparties_set",
                        lambda: {"BEBOP LTD", "0XRICK LIMITED"})
    monkeypatch.setattr(cashflow_db, "_load_portfolio_ids_set",
                        lambda: {8006, 8041, 8888})
    monkeypatch.setattr(cashflow_db, "_load_accounts_set",
                        lambda: {"TK818@BINANCE", "WALLET_CDA_EVM_04"})
    monkeypatch.setattr(cashflow_db, "_load_assets_set",
                        lambda: {"USDC", "USDT", "ETH", "BTC"})


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
        "account_type": "EXCHANGE",
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
        "account_type": "EXCHANGE",
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
    """The server enforces the same cashflow_type enum the form's dropdown
    uses, so a non-standard type gets a 400 instead of silently passing
    through to a draft with a blank dropdown for the human reviewer."""
    payload = {
        "cashflow_type": "MADE UP TYPE",  # not in the enum
        "direction": "OUTGOING",
        "entity": "TOKKA LABS PTE LTD",
        "portfolio_id": 8888,
        "portfolio_name": "TOKKA LABS - TREASURY",
        "counterparty": "BEBOP LTD",
        "account": "TK818@BINANCE",
        "account_type": "EXCHANGE",
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
        "account_type": "EXCHANGE",
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


VALID_SPOT_DRAFT_PAYLOAD = {
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
    "user_id": "claude:danny.pang",
    "status": "PENDING",
}


def test_validate_payload_for_category_spot_passes():
    """SPOT now delegates to spot_db.validate_payload(mode='insert').
    A structurally complete SPOT payload should not raise."""
    draft_db.validate_payload_for_category("SPOT", VALID_SPOT_DRAFT_PAYLOAD)  # no raise


def test_validate_payload_for_category_spot_same_asset_raises():
    bad = {**VALID_SPOT_DRAFT_PAYLOAD, "quote_asset": "USDG"}
    with pytest.raises(draft_db.ValidationError, match="differ"):
        draft_db.validate_payload_for_category("SPOT", bad)


def test_validate_payload_for_category_spot_missing_field_raises():
    bad = {k: v for k, v in VALID_SPOT_DRAFT_PAYLOAD.items() if k != "price"}
    with pytest.raises(draft_db.ValidationError, match="price"):
        draft_db.validate_payload_for_category("SPOT", bad)


def test_validate_payload_for_category_unknown_raises():
    with pytest.raises(draft_db.ValidationError, match="unknown category"):
        draft_db.validate_payload_for_category("FUTURES", {})


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


# ── On-behalf-of booking (resolve_booker) ───────────────────────────

def _users(*names):
    return lambda u: next((n for n in names if n.lower() == u.lower()), None)


def test_resolve_booker_defaults_to_the_acting_user():
    payload = {"amount": "1"}
    assert draft_db.resolve_booker(payload, "danny.pang", "bearer", _users()) == ("danny.pang", payload)
    assert draft_db.resolve_booker(payload, "danny.pang", "cookie", _users()) == ("danny.pang", payload)
    assert draft_db.resolve_booker(None, "danny.pang", "bearer", _users()) == ("danny.pang", None)


def test_resolve_booker_honours_requested_by_for_bearer_callers():
    booker, payload = draft_db.resolve_booker(
        {"amount": "1", "requested_by": "Irven.Heng"}, "danny.pang", "bearer",
        _users("irven.heng"))
    assert booker == "irven.heng"          # the DB's spelling, not the caller's
    assert payload == {"amount": "1"}      # the field never reaches the row


def test_resolve_booker_blank_requested_by_is_ignored():
    for blank in (None, ""):
        booker, payload = draft_db.resolve_booker(
            {"amount": "1", "requested_by": blank}, "danny.pang", "bearer", _users())
        assert booker == "danny.pang" and payload == {"amount": "1"}


def test_resolve_booker_refuses_cookie_sessions():
    for mode in ("cookie", None):
        with pytest.raises(draft_db.ValidationError, match="API-token callers"):
            draft_db.resolve_booker({"requested_by": "irven.heng"}, "danny.pang", mode,
                                    _users("irven.heng"))


def test_resolve_booker_refuses_unknown_or_inactive_users():
    with pytest.raises(draft_db.ValidationError, match="not an active MO user"):
        draft_db.resolve_booker({"requested_by": "nobody"}, "danny.pang", "bearer",
                                _users("irven.heng"))


@pytest.mark.parametrize("bad", [" ", "a b", "x" * 65, 42, "irven;drop", "a@b.com"])
def test_resolve_booker_rejects_malformed_names(bad):
    with pytest.raises(draft_db.ValidationError, match="invalid requested_by"):
        draft_db.resolve_booker({"requested_by": bad}, "danny.pang", "bearer", _users())


def test_resolve_booker_does_not_mutate_the_caller_payload():
    src = {"amount": "1", "requested_by": "irven.heng"}
    draft_db.resolve_booker(src, "danny.pang", "bearer", _users("irven.heng"))
    assert "requested_by" in src
