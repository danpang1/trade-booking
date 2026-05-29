"""Pure-logic unit tests for binance_vip_loan_ltv credential parsing.

Covers _creds_from_doc, which selects the Binance account out of the
prod gw_secret.json (many CEX accounts keyed by internal id) and stays
tolerant of the older flat/nested shapes. No network or Vault required.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import binance_vip_loan_ltv as mod  # noqa: E402


# ── prod shape: many accounts keyed by internal id ──────────────────

def test_id_keyed_map_picks_the_right_account():
    """135 (tk818) is selected; ak/sk map to (api_key, api_secret)."""
    doc = {
        "135": {"account-type": "sub", "ak": "KEY_135", "sk": "SEC_135"},
        "136": {"account-type": "sub", "ak": "KEY_136", "sk": "SEC_136"},
    }
    assert mod._creds_from_doc(doc, "135") == ("KEY_135", "SEC_135")


def test_id_keyed_map_other_id():
    """The selector, not insertion order, decides which account wins."""
    doc = {
        "135": {"ak": "KEY_135", "sk": "SEC_135"},
        "136": {"ak": "KEY_136", "sk": "SEC_136"},
    }
    assert mod._creds_from_doc(doc, "136") == ("KEY_136", "SEC_136")


def test_kv_v2_wrapper_is_unwrapped():
    """KV v2 renders {'data': {...}, 'metadata': {...}} — unwrap to data."""
    doc = {
        "data": {"135": {"ak": "KEY", "sk": "SEC"}},
        "metadata": {"version": 3},
    }
    assert mod._creds_from_doc(doc, "135") == ("KEY", "SEC")


def test_unknown_account_id_returns_none():
    doc = {"135": {"ak": "KEY", "sk": "SEC"}}
    assert mod._creds_from_doc(doc, "999") is None


def test_account_missing_secret_returns_none():
    doc = {"135": {"ak": "KEY"}}
    assert mod._creds_from_doc(doc, "135") is None


# ── backward-compatible shapes ──────────────────────────────────────

def test_nested_binance_object():
    doc = {"binance": {"api_key": "KEY", "api_secret": "SEC"}}
    assert mod._creds_from_doc(doc, "135") == ("KEY", "SEC")


def test_flat_keys():
    doc = {"binance_api_key": "KEY", "binance_api_secret": "SEC"}
    assert mod._creds_from_doc(doc, "135") == ("KEY", "SEC")


def test_flat_uppercase_keys():
    doc = {"BINANCE_API_KEY": "KEY", "BINANCE_API_SECRET": "SEC"}
    assert mod._creds_from_doc(doc, "135") == ("KEY", "SEC")


# ── id selection takes priority over the legacy fallbacks ───────────

def test_id_match_wins_over_flat_fallback():
    doc = {
        "135": {"ak": "ID_KEY", "sk": "ID_SEC"},
        "binance_api_key": "FLAT_KEY",
        "binance_api_secret": "FLAT_SEC",
    }
    assert mod._creds_from_doc(doc, "135") == ("ID_KEY", "ID_SEC")


# ── junk inputs ─────────────────────────────────────────────────────

def test_non_dict_returns_none():
    assert mod._creds_from_doc(["not", "a", "dict"], "135") is None
    assert mod._creds_from_doc(None, "135") is None


def test_empty_dict_returns_none():
    assert mod._creds_from_doc({}, "135") is None


# ── Vault mount path: must prefer the plural default ────────────────

def test_vault_candidate_paths_prefer_plural():
    """Vault's default mount is /vault/secrets/ (plural); singular is the
    fallback. Reading the wrong one was the original prod bug."""
    paths = [p.as_posix() for p in mod.VAULT_SECRET_CANDIDATES]
    assert "/vault/secrets/gw_secret.json" in paths
    assert paths.index("/vault/secrets/gw_secret.json") == 0
