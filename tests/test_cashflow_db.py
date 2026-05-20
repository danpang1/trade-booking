"""Tests for trade-booking/scripts/cashflow_db.py — pure-logic functions only.
DB-touching scripts (cashflow_insert, cashflow_amend, etc.) are smoke-tested
manually against UAT; see their docstrings.
"""
from pathlib import Path
import sys
from datetime import datetime, timezone
from decimal import Decimal

import pytest

# Make the trade-booking scripts importable
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import cashflow_db  # noqa: E402


def test_load_creds_parses_mo_db_uat_block(tmp_path: Path, monkeypatch):
    fake_env = tmp_path / ".env"
    fake_env.write_text(
        "# Some other section\n"
        "key: value\n"
        "\n"
        "# MO DB UAT\n"
        "MO_DB_HOST: db.example.com\n"
        "MO_DB_PORT: 5432\n"
        "MO_DB_DATABASE: mo_uat\n"
        "MO_DB_USERNAME: app\n"
        "MO_DB_PASSWORD: secret\n"
        "\n"
        "# Another section after\n"
        "other: thing\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cashflow_db, "ENV", fake_env)
    c = cashflow_db.load_creds()
    assert c == {
        "host": "db.example.com",
        "port": "5432",
        "database": "mo_uat",
        "username": "app",
        "password": "secret",
    }


def test_load_creds_raises_when_block_missing(tmp_path: Path, monkeypatch):
    fake_env = tmp_path / ".env"
    fake_env.write_text("# Other section\nkey: value\n", encoding="utf-8")
    monkeypatch.setattr(cashflow_db, "ENV", fake_env)
    with pytest.raises(RuntimeError, match="MO DB UAT"):
        cashflow_db.load_creds()


def test_load_creds_raises_when_env_missing(tmp_path: Path, monkeypatch):
    missing = tmp_path / "nope.env"
    monkeypatch.setattr(cashflow_db, "ENV", missing)
    # Clear any MO_DB_* env vars so we hit the FileNotFoundError path.
    for k in ("HOST", "PORT", "DATABASE", "USERNAME", "PASSWORD"):
        monkeypatch.delenv(f"MO_DB_{k}", raising=False)
    with pytest.raises(FileNotFoundError):
        cashflow_db.load_creds()


def test_load_creds_env_vars_take_precedence(tmp_path: Path, monkeypatch):
    """When all required MO_DB_* env vars are set, .env is not read."""
    # Point ENV at a non-existent path — if env vars don't take precedence,
    # this would raise FileNotFoundError.
    monkeypatch.setattr(cashflow_db, "ENV", tmp_path / "nope.env")
    monkeypatch.setenv("MO_DB_HOST", "env-host.example.com")
    monkeypatch.setenv("MO_DB_DATABASE", "env_db")
    monkeypatch.setenv("MO_DB_USERNAME", "env_user")
    monkeypatch.setenv("MO_DB_PASSWORD", "env_pass")
    # MO_DB_PORT intentionally unset — should default to 5432
    monkeypatch.delenv("MO_DB_PORT", raising=False)
    c = cashflow_db.load_creds()
    assert c == {
        "host": "env-host.example.com",
        "port": "5432",
        "database": "env_db",
        "username": "env_user",
        "password": "env_pass",
    }


def test_load_creds_partial_env_vars_fall_back_to_dotenv(tmp_path: Path, monkeypatch):
    """If env vars are incomplete, .env should be read."""
    fake_env = tmp_path / ".env"
    fake_env.write_text(
        "# MO DB UAT\n"
        "MO_DB_HOST: file-host.example.com\n"
        "MO_DB_DATABASE: file_db\n"
        "MO_DB_USERNAME: file_user\n"
        "MO_DB_PASSWORD: file_pass\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cashflow_db, "ENV", fake_env)
    # Only HOST set — incomplete, must fall back to .env
    monkeypatch.setenv("MO_DB_HOST", "env-host-ignored")
    for k in ("PORT", "DATABASE", "USERNAME", "PASSWORD"):
        monkeypatch.delenv(f"MO_DB_{k}", raising=False)
    c = cashflow_db.load_creds()
    assert c["host"] == "file-host.example.com"  # from .env, not env var
    assert c["database"] == "file_db"


def _valid_insert_payload() -> dict:
    return {
        "deal_ref": "MCF-PLACEHOLDER",          # ignored on insert
        "external_trade_id": None,
        "cashflow_type": "FUNDING IN",
        "direction": "INCOMING",
        "entity": "TK006",
        "portfolio_id": 8006,
        "portfolio_name": "CDA",
        "counterparty": "Galaxy",
        "account": "WALLET_CDA_EVM_04",
        "account_type": "WALLET",
        "asset": "USDC",
        "amount": "1000000",
        "fee_asset": None,
        "fee_amount": "0",
        "trade_date": "2026-05-15T12:00:00Z",
        "value_date": "2026-05-15T12:00:00Z",
        "network": "BSC",
        "txid_reference": None,
        "user_id": "adam",
        "status": "CONFIRMED",
        "comment": None,
    }


def test_validate_insert_accepts_valid_payload():
    p = _valid_insert_payload()
    cashflow_db.validate_payload(p, mode="insert")  # no raise


def test_validate_insert_rejects_missing_required():
    p = _valid_insert_payload()
    p["asset"] = None
    with pytest.raises(cashflow_db.ValidationError, match="asset"):
        cashflow_db.validate_payload(p, mode="insert")


def test_validate_insert_rejects_bad_direction():
    p = _valid_insert_payload()
    p["direction"] = "SEND"
    with pytest.raises(cashflow_db.ValidationError, match="direction"):
        cashflow_db.validate_payload(p, mode="insert")


def test_validate_insert_rejects_bad_status():
    p = _valid_insert_payload()
    p["status"] = "DRAFT"
    with pytest.raises(cashflow_db.ValidationError, match="status"):
        cashflow_db.validate_payload(p, mode="insert")


def test_validate_insert_rejects_non_numeric_amount():
    p = _valid_insert_payload()
    p["amount"] = "not-a-number"
    with pytest.raises(cashflow_db.ValidationError, match="amount"):
        cashflow_db.validate_payload(p, mode="insert")


def test_validate_insert_accepts_mirror_leg_array():
    a = _valid_insert_payload()
    b = _valid_insert_payload()
    b["direction"] = "OUTGOING"
    cashflow_db.validate_payload([a, b], mode="insert")  # no raise


def test_validate_insert_rejects_mirror_leg_wrong_length():
    a = _valid_insert_payload()
    with pytest.raises(cashflow_db.ValidationError, match="mirror"):
        cashflow_db.validate_payload([a], mode="insert")


def _valid_amend_payload() -> dict:
    p = _valid_insert_payload()
    p["deal_ref"] = "MCF-42"   # amend identifies the row to close
    return p


def test_validate_amend_accepts_valid_payload():
    cashflow_db.validate_payload(_valid_amend_payload(), mode="amend")  # no raise


def test_validate_amend_rejects_missing_deal_ref():
    p = _valid_amend_payload()
    p["deal_ref"] = None
    with pytest.raises(cashflow_db.ValidationError, match="deal_ref"):
        cashflow_db.validate_payload(p, mode="amend")


def test_validate_amend_rejects_list_payload():
    a = _valid_amend_payload()
    with pytest.raises(cashflow_db.ValidationError, match="mirror"):
        cashflow_db.validate_payload([a, a], mode="amend")


def test_payload_to_columns_orders_match_ddl():
    p = _valid_insert_payload()
    cols, vals = cashflow_db.payload_to_columns(p, deal_ref="MCF-42")
    # Column order MUST match apply_schema_cashflow.py DDL declaration
    # order. effective_start/effective_end are SQL expressions, NOT params.
    assert cols == (
        "deal_ref", "external_trade_id", "txn_type", "cashflow_type",
        "direction", "entity", "portfolio_id", "portfolio_name",
        "counterparty_id", "counterparty", "account", "account_type", "asset", "amount",
        "fee_asset", "fee_amount", "trade_date", "value_date", "network",
        "txid_reference", "user_id", "status", "comment",
    )
    # Values must align positionally with cols.
    assert vals[cols.index("deal_ref")] == "MCF-42"
    assert vals[cols.index("txn_type")] == "CASHFLOW"
    assert vals[cols.index("cashflow_type")] == "FUNDING IN"
    assert vals[cols.index("direction")] == "INCOMING"
    assert vals[cols.index("portfolio_id")] == "8006"  # stored as TEXT
    assert vals[cols.index("amount")] == "1000000"
    assert vals[cols.index("fee_amount")] == "0"


def test_payload_to_columns_coerces_empty_strings_to_none():
    p = _valid_insert_payload()
    p["external_trade_id"] = ""
    p["txid_reference"] = ""
    cols, vals = cashflow_db.payload_to_columns(p, deal_ref="MCF-42")
    assert vals[cols.index("external_trade_id")] is None
    assert vals[cols.index("txid_reference")] is None


def test_payload_to_columns_defaults_fee_amount_zero():
    p = _valid_insert_payload()
    p["fee_amount"] = None
    cols, vals = cashflow_db.payload_to_columns(p, deal_ref="MCF-42")
    assert vals[cols.index("fee_amount")] == "0"


def test_row_to_payload_serializes_types_for_json():
    # Simulate the row tuple as psycopg2 returns it. Column order
    # = DDL order = DATA_COLUMNS with effective_start/effective_end
    # inserted just before user_id.
    user_id_idx = cashflow_db.DATA_COLUMNS.index("user_id")
    cols = (
        cashflow_db.DATA_COLUMNS[:user_id_idx]
        + ("effective_start", "effective_end")
        + cashflow_db.DATA_COLUMNS[user_id_idx:]
    )
    row = (
        "MCF-42",                # deal_ref
        None,                    # external_trade_id
        "CASHFLOW",              # txn_type
        "FUNDING IN",            # cashflow_type
        "INCOMING",              # direction
        "TK006",                 # entity
        "8006",                  # portfolio_id (TEXT column)
        "CDA",                   # portfolio_name
        "CID000001",             # counterparty_id (CID + 6-digit)
        "Galaxy",                # counterparty
        "WALLET_CDA_EVM_04",     # account
        "WALLET",                # account_type
        "USDC",                  # asset
        Decimal("1000000"),      # amount
        None,                    # fee_asset
        Decimal("0"),            # fee_amount
        datetime(2026, 5, 15, 12, tzinfo=timezone.utc),  # trade_date
        datetime(2026, 5, 15, 12, tzinfo=timezone.utc),  # value_date
        "BSC",                   # network
        None,                    # txid_reference
        datetime(2026, 5, 15, 14, 23, 1, tzinfo=timezone.utc),  # effective_start
        None,                    # effective_end
        "adam",                  # user_id
        "CONFIRMED",             # status
        None,                    # comment
    )
    out = cashflow_db.row_to_payload(cols, row)
    assert out["deal_ref"] == "MCF-42"
    assert out["portfolio_id"] == "8006"  # TEXT column → string in JSON
    assert out["amount"] == "1000000"               # Decimal → string for JSON
    assert out["fee_amount"] == "0"
    assert out["trade_date"] == "2026-05-15T12:00:00+00:00"
    assert out["effective_start"] == "2026-05-15T14:23:01+00:00"
    assert out["effective_end"] is None
    assert out["counterparty"] == "Galaxy"
    assert out["counterparty_id"] == "CID000001"
