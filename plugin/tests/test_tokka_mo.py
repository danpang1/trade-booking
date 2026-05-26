"""Pure-logic tests for tokka-mo CLI. No HTTP. Hermetic filesystem via tmp_path."""
import importlib.util
import importlib.machinery
import json
import os
import sys
import stat
from pathlib import Path

import pytest


# Load the CLI from bin/tokka-mo. The file has no .py extension, so
# spec_from_file_location can't infer a loader — we pass SourceFileLoader
# explicitly.
ROOT = Path(__file__).resolve().parents[1]
_TOKKA_MO_PATH = ROOT / "bin" / "tokka-mo"
_LOADER = importlib.machinery.SourceFileLoader("tokka_mo", str(_TOKKA_MO_PATH))
SPEC = importlib.util.spec_from_loader("tokka_mo", _LOADER)
tokka_mo = importlib.util.module_from_spec(SPEC)
sys.modules["tokka_mo"] = tokka_mo
SPEC.loader.exec_module(tokka_mo)


@pytest.fixture
def hermetic_config(tmp_path, monkeypatch):
    """Redirect $CREDS / $CACHE to a tmp dir so tests don't touch real config."""
    monkeypatch.setenv("TOKKA_MO_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("TOKKA_MO_CACHE_DIR", str(tmp_path / "cache"))
    return tmp_path


# ── Credential storage ─────────────────────────────────────────────

def test_load_credentials_missing_raises(hermetic_config):
    with pytest.raises(tokka_mo.CredsMissing):
        tokka_mo.load_credentials()


def test_save_then_load_round_trip(hermetic_config):
    creds = {
        "api_url": "https://mo-tools-uat.tokkalabs.com",
        "username": "alice",
        "token": "tkmo_abc123",
        "prefix": "tkmo_abc1",
        "token_id": 42,
        "expires_at": "2026-08-23T00:00:00+00:00",
    }
    tokka_mo.save_credentials(creds)
    loaded = tokka_mo.load_credentials()
    assert loaded == creds


def test_save_credentials_chmod_600(hermetic_config):
    # Skip on Windows — chmod semantics differ
    if os.name == "nt":
        pytest.skip("POSIX-only chmod check")
    tokka_mo.save_credentials({
        "api_url": "x", "username": "y", "token": "z",
        "prefix": "p", "token_id": 1, "expires_at": "t",
    })
    path = Path(os.environ["TOKKA_MO_CONFIG_DIR"]) / "credentials"
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_clear_credentials_removes_file(hermetic_config):
    tokka_mo.save_credentials({
        "api_url": "x", "username": "y", "token": "z",
        "prefix": "p", "token_id": 1, "expires_at": "t",
    })
    tokka_mo.clear_credentials()
    with pytest.raises(tokka_mo.CredsMissing):
        tokka_mo.load_credentials()


def test_clear_credentials_idempotent_when_absent(hermetic_config):
    # Should NOT raise even if file never existed.
    tokka_mo.clear_credentials()


# ── _extract_sid parser ─────────────────────────────────────────

def test_extract_sid_basic():
    h = "sid=abc123; HttpOnly; SameSite=Lax; Path=/; Max-Age=43200"
    assert tokka_mo._extract_sid(h) == "abc123"


def test_extract_sid_missing():
    assert tokka_mo._extract_sid("") is None
    assert tokka_mo._extract_sid("Other=foo") is None


def test_extract_sid_empty_value():
    # Logout-style cookie: sid=
    assert tokka_mo._extract_sid("sid=; Max-Age=0") is None


# ── Refdata cache ──────────────────────────────────────────────

def test_is_cache_fresh_returns_true_within_24h(hermetic_config):
    import datetime as dt
    cache = {"fetched_at": dt.datetime(2026, 5, 25, 12, 0, 0, tzinfo=dt.timezone.utc).isoformat()}
    now = dt.datetime(2026, 5, 25, 23, 0, 0, tzinfo=dt.timezone.utc)
    assert tokka_mo.is_cache_fresh(cache, now=now) is True


def test_is_cache_fresh_returns_false_after_24h(hermetic_config):
    import datetime as dt
    cache = {"fetched_at": dt.datetime(2026, 5, 24, 12, 0, 0, tzinfo=dt.timezone.utc).isoformat()}
    now = dt.datetime(2026, 5, 25, 13, 0, 0, tzinfo=dt.timezone.utc)  # 25h later
    assert tokka_mo.is_cache_fresh(cache, now=now) is False


def test_is_cache_fresh_handles_missing_field(hermetic_config):
    assert tokka_mo.is_cache_fresh({}, now=None) is False
    assert tokka_mo.is_cache_fresh({"fetched_at": ""}, now=None) is False
    assert tokka_mo.is_cache_fresh({"fetched_at": "not-a-date"}, now=None) is False


def test_save_and_reload_refdata_cache(hermetic_config):
    data = {
        "fetched_at": "2026-05-25T12:00:00+00:00",
        "portfolios": [{"id": 8006, "name": "CDA"}],
        "accounts": [{"id": 1, "name": "BINANCE TK006"}],
        "counterparties": [{"id": 1, "name": "Galaxy"}],
        "users": [{"id": 1, "name": "danny.pang"}],
        "tokens": [{"symbol": "USDC"}],
    }
    tokka_mo.save_refdata_cache(data)
    loaded = tokka_mo.load_refdata_cache()
    assert loaded == data


def test_load_refdata_cache_returns_none_when_missing(hermetic_config):
    assert tokka_mo.load_refdata_cache() is None


# ── CASHFLOW payload validator ──────────────────────────────────

REFDATA_FIXTURE = {
    "portfolios": [
        {"id": 8006, "name": "CDA"},
        {"id": 8041, "name": "MARKET MAKING"},
    ],
    "accounts": [
        {"name": "TK006@BINANCE"},
        {"name": "TK818@BINANCE"},
        {"name": "TOKKA TREASURY WALLET"},
    ],
    "counterparties": [
        {"name": "Galaxy"},
        {"name": "TOKKA TREASURY"},
        {"name": "TOKKA LABS PTE LTD"},
    ],
    "tokens": [
        {"symbol": "USDC"},
        {"symbol": "USDT"},
        {"symbol": "BEBOP"},
    ],
    "users": [{"username": "danny.pang"}],
    "fetched_at": "2026-05-26T00:00:00+00:00",
}

VALID_PAYLOAD = {
    "cashflow_type": "OPEX",
    "direction": "OUTGOING",
    "entity": "TOKKA LABS PTE LTD",
    "portfolio_id": 8006,
    "portfolio_name": "CDA",
    "counterparty": "TOKKA TREASURY",
    "account": "TOKKA TREASURY WALLET",
    "account_type": "WALLET",
    "asset": "USDC",
    "amount": "888",
    "trade_date": "2026-05-26T12:00:00+00:00",
    "value_date": "2026-05-26T12:00:00+00:00",
    "user_id": "danny.pang",
    "status": "PENDING",
}


def test_validate_cashflow_payload_happy_path():
    tokka_mo.validate_cashflow_payload(VALID_PAYLOAD, REFDATA_FIXTURE)


@pytest.mark.parametrize("field", [
    "cashflow_type", "direction", "entity", "portfolio_id", "portfolio_name",
    "counterparty", "account", "account_type", "asset", "amount",
    "trade_date", "value_date", "user_id", "status",
])
def test_validate_missing_required_field_raises(field):
    bad = {k: v for k, v in VALID_PAYLOAD.items() if k != field}
    with pytest.raises(tokka_mo.ValidationError, match=field):
        tokka_mo.validate_cashflow_payload(bad, REFDATA_FIXTURE)


def test_validate_bad_direction():
    bad = {**VALID_PAYLOAD, "direction": "IN"}
    with pytest.raises(tokka_mo.ValidationError, match="direction"):
        tokka_mo.validate_cashflow_payload(bad, REFDATA_FIXTURE)


def test_validate_bad_account_type():
    bad = {**VALID_PAYLOAD, "account_type": "POCKET"}
    with pytest.raises(tokka_mo.ValidationError, match="account_type"):
        tokka_mo.validate_cashflow_payload(bad, REFDATA_FIXTURE)


def test_validate_zero_amount():
    bad = {**VALID_PAYLOAD, "amount": "0"}
    with pytest.raises(tokka_mo.ValidationError, match="amount"):
        tokka_mo.validate_cashflow_payload(bad, REFDATA_FIXTURE)


def test_validate_portfolio_not_in_refdata():
    bad = {**VALID_PAYLOAD, "portfolio_id": 9999}
    with pytest.raises(tokka_mo.ValidationError, match="portfolio_id"):
        tokka_mo.validate_cashflow_payload(bad, REFDATA_FIXTURE)


def test_validate_counterparty_not_in_refdata():
    bad = {**VALID_PAYLOAD, "counterparty": "TOTALLY MADE UP CO"}
    with pytest.raises(tokka_mo.ValidationError, match="counterparty"):
        tokka_mo.validate_cashflow_payload(bad, REFDATA_FIXTURE)


def test_validate_asset_not_in_refdata():
    bad = {**VALID_PAYLOAD, "asset": "DOGECOIN"}
    with pytest.raises(tokka_mo.ValidationError, match="asset"):
        tokka_mo.validate_cashflow_payload(bad, REFDATA_FIXTURE)
