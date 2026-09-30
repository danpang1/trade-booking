"""manual_transfer row building (pure, no DB): which end is ours, sign, fee
on the outgoing leg only, status mapping and the entry_uid identity."""
from __future__ import annotations
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import manual_write  # noqa: E402


def _row(**over) -> dict:
    """An MO transfer row as transfer_db.row_to_payload returns it: the
    OUTGOING leg of 250 USDT from WALLET_CRB_EVM_02 to WALLET_CRB_EVM_03."""
    r = {
        "deal_ref": "MTR00000157",
        "transfer_type": "INTERNAL",
        "direction": "OUTGOING",
        "source_account_name": "WALLET_CRB_EVM_02",
        "source_product": "ETHEREUM",
        "source_account_id": "21001",
        "dest_account_name": "WALLET_CRB_EVM_03",
        "dest_product": "BINANCE SMART CHAIN",
        "dest_account_id": "22004",
        "asset": "USDT",
        "amount": "-250",
        "fee_asset": "USDT",
        "fee_amount": "1.5",
        "initiated_datetime": "2026-09-30T10:00:00+00:00",
        "completed_datetime": None,
        "network": "ETHEREUM",
        "ext_transfer_id": "0xabc",
        "effective_start": "2026-09-30T10:00:05+00:00",
        "effective_end": None,
        "user_id": "danny.pang",
        "status": "COMPLETED",
        "comment": None,
        "internal_journal": None,
    }
    r.update(over)
    return r


def test_internal_outgoing_leg():
    c = manual_write.build_manual_transfer_row(
        _row(), asset_id=7, fee_asset_id=7, pair_deal_ref="MTR00000158"
    )
    assert (c["source_account_id"], c["dest_account_id"]) == ("21001", "22004")
    assert "account_id" not in c
    assert c["direction"] == "OUTGOING"
    assert c["amount"] == Decimal("-250")
    assert (c["fee_amount"], c["fee_asset_id"]) == (Decimal("1.5"), 7)
    assert c["transfer_type"] == "internal" and c["status"] == "completed"
    assert c["pair_deal_ref"] == "MTR00000158"
    assert c["internal_journal"] is False
    # No completion time yet: position orders by the initiation time.
    assert c["ts_exchange_event"] == "2026-09-30T10:00:00+00:00"
    assert c["ts_completed"] is None


def test_every_tms_field_is_carried():
    """Nothing TMS booked is lost: both ends' ids verbatim, updated_by too.
    Names / products are derivable and not stored."""
    r = _row(updated_by="francis", comment="c")
    c = manual_write.build_manual_transfer_row(r, asset_id=7, fee_asset_id=7)
    for f in ("source_account_id", "dest_account_id",
              "ext_transfer_id", "network", "comment", "updated_by"):
        assert c[f] == r[f], f
    for f in ("source_account_name", "source_product", "dest_account_name", "dest_product"):
        assert f not in c, f
    assert c["booked_by"] == r["user_id"]
    assert c["ts_initiated"] == r["initiated_datetime"]


def test_incoming_leg_keeps_the_fee_as_booked():
    """E.g. the counterparty's fee on a deposit: stored, not charged to us
    (position charges a fee only on an outgoing leg)."""
    c = manual_write.build_manual_transfer_row(
        _row(direction="INCOMING", amount="250"), asset_id=7, fee_asset_id=7
    )
    assert c["amount"] == Decimal("250")
    assert (c["fee_amount"], c["fee_asset_id"]) == (Decimal("1.5"), 7)


def test_zero_fee_is_no_fee():
    c = manual_write.build_manual_transfer_row(_row(fee_amount="0"), asset_id=7, fee_asset_id=None)
    assert (c["fee_amount"], c["fee_asset_id"]) == (None, None)


def test_external_incoming_uses_the_dest_end():
    """A deposit: the source is the counterparty, the dest is ours."""
    c = manual_write.build_manual_transfer_row(
        _row(
            transfer_type="EXTERNAL", direction="INCOMING", amount="12",
            source_account_name="BINANCE", source_product=None, source_account_id="0xfeed",
            dest_account_name="TK810@BINANCE", dest_product="SPOT", dest_account_id="3001",
            completed_datetime="2026-09-30T10:30:00+00:00", internal_journal="Y",
        ),
        asset_id=7, fee_asset_id=None,
    )
    assert (c["source_account_id"], c["dest_account_id"]) == ("0xfeed", "3001")
    assert c["transfer_type"] == "external" and c["amount"] == Decimal("12")
    assert c["ts_exchange_event"] == "2026-09-30T10:30:00+00:00"
    assert c["internal_journal"] is True


def test_external_outgoing_uses_the_source_end():
    c = manual_write.build_manual_transfer_row(
        _row(transfer_type="EXTERNAL", dest_account_name="BINANCE",
             dest_product=None, dest_account_id="0xabc"),
        asset_id=7, fee_asset_id=7,
    )
    assert (c["source_account_id"], c["dest_account_id"]) == ("21001", "0xabc")


def test_own_end_without_gateway_id_is_refused():
    """A BANK account (or an unresolvable one) has no position balance key."""
    with pytest.raises(ValueError, match="no gateway account_id"):
        manual_write.build_manual_transfer_row(_row(source_account_id=None), asset_id=7, fee_asset_id=7)


def test_entry_uid_is_per_version():
    a = manual_write.build_manual_transfer_row(_row(), asset_id=7, fee_asset_id=7)
    again = manual_write.build_manual_transfer_row(_row(), asset_id=7, fee_asset_id=7)
    amended = manual_write.build_manual_transfer_row(
        _row(effective_start="2026-09-30T11:00:00+00:00"), asset_id=7, fee_asset_id=7
    )
    assert a["entry_uid"] == again["entry_uid"]
    assert a["entry_uid"] != amended["entry_uid"]


@pytest.mark.parametrize("tms,want", [
    ("PENDING", "pending"), ("CONFIRMED", "confirmed"),
    ("COMPLETED", "completed"), ("cancelled", "cancelled"),
])
def test_map_transfer_status(tms, want):
    assert manual_write.map_transfer_status(tms) == want


def test_map_transfer_status_rejects_cashflow_statuses():
    with pytest.raises(ValueError):
        manual_write.map_transfer_status("SETTLED")


def _stub_refdata(monkeypatch):
    files = {
        "accounts.json": {
            "wallet": [
                {"name": "WALLET_CRB_EVM_02", "portfolio": "TOKKA LABS - MM - CENTRAL RISK BOOK"},
                {"name": "WALLET_CRB_EVM_03", "portfolio": "TOKKA LABS - TREASURY"},
            ],
            "bank": [{"name": "DBS BANK", "portfolio": ""}],
        },
        "portfolios.json": [
            {"name": "TOKKA LABS - MM - CENTRAL RISK BOOK", "number": 8041},
            {"name": "TOKKA LABS - TREASURY", "number": 9000},
        ],
        "counterparties.json": [{"id": 56, "name": "BINANCE"}],
    }
    monkeypatch.setattr(manual_write, "_load_refdata", lambda name: files.get(name, []))


def test_attribution_internal_uses_our_end_portfolio_and_no_counterparty(monkeypatch):
    _stub_refdata(monkeypatch)
    assert manual_write.resolve_transfer_attribution(_row()) == {
        "portfolio_id": 8041, "counterparty_id": None,
    }
    # The mirror leg reads from the receiver: its own portfolio.
    mirror = _row(direction="INCOMING", amount="250",
                  source_account_name="WALLET_CRB_EVM_03",
                  dest_account_name="WALLET_CRB_EVM_02")
    assert manual_write.resolve_transfer_attribution(mirror)["portfolio_id"] == 9000


def test_attribution_external_resolves_the_counterparty(monkeypatch):
    _stub_refdata(monkeypatch)
    deposit = _row(transfer_type="EXTERNAL", direction="INCOMING", amount="12",
                   source_account_name="BINANCE", dest_account_name="WALLET_CRB_EVM_03")
    assert manual_write.resolve_transfer_attribution(deposit) == {
        "portfolio_id": 9000, "counterparty_id": 56,
    }


def test_attribution_unmatched_is_none(monkeypatch):
    """A BANK account names only its entity; an unknown name has no id."""
    _stub_refdata(monkeypatch)
    out = manual_write.resolve_transfer_attribution(
        _row(transfer_type="EXTERNAL", source_account_name="DBS BANK",
             dest_account_name="NOT A COUNTERPARTY")
    )
    assert out == {"portfolio_id": None, "counterparty_id": None}


def test_attribution_against_the_shipped_refdata():
    """No stub: the real refdata files resolve a known account and counterparty."""
    accounts = manual_write._load_refdata("accounts.json")
    ptfs = {p["name"]: p["number"] for p in manual_write._load_refdata("portfolios.json")}
    acct = next(a for a in accounts["exchange"] if a.get("portfolio") in ptfs)
    cp = manual_write._load_refdata("counterparties.json")[0]
    out = manual_write.resolve_transfer_attribution(
        _row(transfer_type="EXTERNAL", source_account_name=acct["name"],
             dest_account_name=cp["name"])
    )
    assert out == {"portfolio_id": int(ptfs[acct["portfolio"]]), "counterparty_id": cp["id"]}


def test_build_carries_attribution():
    c = manual_write.build_manual_transfer_row(
        _row(), asset_id=7, fee_asset_id=7, portfolio_id=8041, counterparty_id=None
    )
    assert (c["portfolio_id"], c["counterparty_id"]) == (8041, None)
