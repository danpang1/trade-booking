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
