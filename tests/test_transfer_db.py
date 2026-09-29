"""Validation contract for transfer.

One row per transfer, both ends on it. EXTERNAL: one end is ours and the
other a refdata counterparty, which end being fixed by direction. INTERNAL:
both ends ours, booked OUTGOING (negative) from the source.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import cashflow_db  # noqa: E402
import transfer_db  # noqa: E402


@pytest.fixture(autouse=True)
def _stub_refdata(monkeypatch):
    """transfer_db validates through cashflow_db's loaders; pin them so the
    checks actually run (an empty set fails open and would mask gaps)."""
    monkeypatch.setattr(cashflow_db, "_load_counterparties_set",
                        lambda: {"BINANCE", "BEBOP LTD"})
    monkeypatch.setattr(cashflow_db, "_load_accounts_set",
                        lambda: {"TK810@BINANCE", "WALLET_CRB_EVM_02", "WALLET_CRB_EVM_03"})
    monkeypatch.setattr(cashflow_db, "_load_assets_set",
                        lambda: {"USDT", "BNB", "ETH"})


def _external(**over) -> dict:
    """Withdrawal: 12 BNB leaves TK810@BINANCE spot for the BINANCE counterparty."""
    p = {
        "transfer_type": "EXTERNAL",
        "direction": "OUTGOING",
        "source_account_name": "TK810@BINANCE",
        "source_product": "SPOT",
        "source_account_id": None,
        "dest_account_name": "BINANCE",
        "dest_product": None,
        "dest_account_id": "0xabc",
        "asset": "BNB",
        "amount": "-12",
        "fee_asset": "BNB",
        "fee_amount": "0.0005",
        "initiated_datetime": "2026-09-28T10:00:00+00:00",
        "completed_datetime": None,
        "network": "BINANCE SMART CHAIN",
        "ext_transfer_id": "wd-123",
        "user_id": "danny.pang",
        "status": "CONFIRMED",
    }
    p.update(over)
    return p


def _internal(**over) -> dict:
    """250 USDT from WALLET_CRB_EVM_02 (ETHEREUM) to WALLET_CRB_EVM_03 (BSC)."""
    p = _external(
        transfer_type="INTERNAL", direction="OUTGOING",
        source_account_name="WALLET_CRB_EVM_02", source_product="ETHEREUM",
        dest_account_name="WALLET_CRB_EVM_03", dest_product="BINANCE SMART CHAIN",
        dest_account_id=None, asset="USDT", amount="-250", network=None,
    )
    p.update(over)
    return p


# ── EXTERNAL ─────────────────────────────────────────────────────────

def test_external_outgoing_ok():
    transfer_db.validate_payload(_external(), mode="insert")


def test_external_incoming_ok():
    """Deposit: the counterparty is the source, our account the dest."""
    transfer_db.validate_payload(_external(
        direction="INCOMING", amount="12",
        source_account_name="BINANCE", source_product=None, source_account_id="0xabc",
        dest_account_name="TK810@BINANCE", dest_product="SPOT", dest_account_id=None,
    ), mode="insert")


def test_external_outgoing_dest_must_be_counterparty():
    with pytest.raises(transfer_db.ValidationError, match="dest_account_name .* counterparties"):
        transfer_db.validate_payload(_external(dest_account_name="WALLET_CRB_EVM_02"), mode="insert")


def test_external_outgoing_source_must_be_ours():
    with pytest.raises(transfer_db.ValidationError, match="source_account_name .* accounts"):
        transfer_db.validate_payload(_external(source_account_name="BINANCE"), mode="insert")


def test_external_incoming_source_must_be_counterparty():
    with pytest.raises(transfer_db.ValidationError, match="source_account_name .* counterparties"):
        transfer_db.validate_payload(_external(direction="INCOMING", amount="12"), mode="insert")


def test_list_payload_rejected():
    with pytest.raises(transfer_db.ValidationError, match="single dict"):
        transfer_db.validate_payload([_external()], mode="insert")


# ── sign / direction ─────────────────────────────────────────────────

def test_outgoing_must_be_negative():
    with pytest.raises(transfer_db.ValidationError, match="sign must follow direction"):
        transfer_db.validate_payload(_external(amount="12"), mode="insert")


def test_incoming_must_be_positive():
    p = _external(direction="INCOMING", amount="-12",
                  source_account_name="BINANCE", dest_account_name="TK810@BINANCE")
    with pytest.raises(transfer_db.ValidationError, match="sign must follow direction"):
        transfer_db.validate_payload(p, mode="insert")


def test_zero_amount_rejected():
    with pytest.raises(transfer_db.ValidationError, match="non-zero"):
        transfer_db.validate_payload(_external(amount="0"), mode="insert")


# ── INTERNAL ─────────────────────────────────────────────────────────

def test_internal_ok():
    transfer_db.validate_payload(_internal(), mode="insert")


def test_internal_is_always_outgoing():
    with pytest.raises(transfer_db.ValidationError, match="booked OUTGOING"):
        transfer_db.validate_payload(_internal(direction="INCOMING", amount="250"), mode="insert")


def test_internal_both_ends_must_be_ours():
    with pytest.raises(transfer_db.ValidationError, match="dest_account_name .* accounts"):
        transfer_db.validate_payload(_internal(dest_account_name="BINANCE"), mode="insert")


def test_internal_same_account_needs_two_products():
    """spot -> funding on one exchange account is a real transfer; the
    same product both ends is the same balance and is refused."""
    same = _internal(source_account_name="TK810@BINANCE", source_product="SPOT",
                     dest_account_name="TK810@BINANCE", dest_product="FUNDING")
    transfer_db.validate_payload(same, mode="insert")
    with pytest.raises(transfer_db.ValidationError, match="two different products"):
        transfer_db.validate_payload({**same, "dest_product": "SPOT"}, mode="insert")


def test_own_sides():
    assert transfer_db.own_sides(_internal()) == ("source", "dest")
    assert transfer_db.own_sides(_external()) == ("source",)
    assert transfer_db.own_sides(_external(direction="INCOMING")) == ("dest",)


def test_amend_requires_deal_ref():
    with pytest.raises(transfer_db.ValidationError, match="deal_ref"):
        transfer_db.validate_payload(_external(), mode="amend")
    transfer_db.validate_payload({**_external(), "deal_ref": "MTR00000001"}, mode="amend")


# ── account ids ──────────────────────────────────────────────────────

def test_stamp_resolves_only_our_ends_and_keeps_typed_ids(monkeypatch):
    import account_id_resolve
    calls = []

    def fake_resolve(name, typ, product):
        calls.append((name, typ, product))
        return f"ID({name}/{product})"

    monkeypatch.setattr(account_id_resolve, "resolve", fake_resolve)
    monkeypatch.setattr(transfer_db, "_load_account_types",
                        lambda: {"TK810@BINANCE": "EXCHANGE"})
    p = _external()
    transfer_db.stamp_account_ids(p)
    assert p["source_account_id"] == "ID(TK810@BINANCE/SPOT)"
    assert p["dest_account_id"] == "0xabc"  # counterparty end untouched
    assert calls == [("TK810@BINANCE", "EXCHANGE", "SPOT")]
    # A hand-set own id is kept on re-stamp.
    p["source_account_id"] = "manual"
    transfer_db.stamp_account_ids(p)
    assert p["source_account_id"] == "manual"


# ── serialisation ────────────────────────────────────────────────────

def test_payload_to_columns_omits_deal_ref_and_uppercases_products():
    cols, vals = transfer_db.payload_to_columns(_external(source_product="spot"))
    assert "deal_ref" not in cols
    d = dict(zip(cols, vals))
    assert d["source_product"] == "SPOT"
    assert d["dest_product"] is None
    assert d["source_account_name"] == "TK810@BINANCE"  # bare, no product baked in
    assert d["fee_amount"] == "0.0005"
    assert len(cols) == len(transfer_db.DATA_COLUMNS) - 1


def test_row_to_payload_adds_enquiry_aliases():
    cols = ("deal_ref", "transfer_type", "direction", "source_account_name",
            "source_product", "dest_account_name", "initiated_datetime", "completed_datetime")
    out = transfer_db.row_to_payload(
        cols, ("MTR00000001", "EXTERNAL", "INCOMING", "BINANCE", None, "TK810@BINANCE", "t0", None))
    assert out["txn_type"] == "TRANSFER"
    assert out["trade_date"] == "t0" and out["value_date"] is None
    # INCOMING: our end is the dest, the far end the source.
    assert out["account"] == "TK810@BINANCE"
    assert out["counterparty"] == "BINANCE"
    out = transfer_db.row_to_payload(
        cols, ("MTR00000002", "INTERNAL", "OUTGOING", "WALLET_CRB_EVM_02", "ETHEREUM", "WALLET_CRB_EVM_03", "t0", None))
    assert out["account"] == "WALLET_CRB_EVM_02 · ETHEREUM"
    assert out["counterparty"] == "WALLET_CRB_EVM_03"


def test_transfer_statuses_are_their_own_set():
    # A transfer either is still moving or has landed: COMPLETED is the
    # terminal good state, and the cashflow-only PROCESSED / SETTLED are out.
    transfer_db.validate_payload(_internal(status="COMPLETED"), mode="insert")
    for bad in ("SETTLED", "PROCESSED"):
        with pytest.raises(transfer_db.ValidationError, match="status must be one of"):
            transfer_db.validate_payload(_internal(status=bad), mode="insert")
