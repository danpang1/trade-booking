"""Pure-logic unit tests for token_db. No DB connection required."""
import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pytest  # noqa: E402  (must follow sys.path.insert above)
import token_db  # noqa: E402


# ── Token generation ──────────────────────────────────────────────

def test_generate_token_format():
    """Plaintext is 'tkmo_' + url-safe random; total length matches spec."""
    t = token_db.generate_token()
    assert t.startswith("tkmo_")
    # url-safe base64 of 32 bytes is 43 chars (no padding). + 5 char prefix = 48.
    assert len(t) == 48
    # url-safe: only [A-Za-z0-9_-]
    assert re.match(r"^tkmo_[A-Za-z0-9_-]+$", t)


def test_generate_token_uniqueness():
    """Two consecutive generations differ (sanity check on randomness)."""
    a = token_db.generate_token()
    b = token_db.generate_token()
    assert a != b


def test_hash_token_is_sha256_hex():
    """Hash is lowercase hex sha256 of the plaintext (64 chars)."""
    t = "tkmo_test_fixed_value_for_hashing_xxxxxxxxxxxxxxx"
    h = token_db.hash_token(t)
    assert len(h) == 64
    assert re.match(r"^[0-9a-f]{64}$", h)
    # Deterministic
    assert token_db.hash_token(t) == h


def test_token_prefix_first_16_chars():
    """The stored 'prefix' is the first 16 chars of plaintext (5 of prefix + 11 random)."""
    t = "tkmo_abcdefghijk_unused_tail"
    assert token_db.token_prefix(t) == "tkmo_abcdefghijk"
    assert len(token_db.token_prefix(t)) == 16


# ── Validators ────────────────────────────────────────────────────

@pytest.mark.parametrize("s", ["My Laptop", "alice's-iPad", "ci_runner_01"])
def test_validate_name_accepts(s):
    assert token_db.validate_name(s) == s


@pytest.mark.parametrize("s", ["", " ", "x" * 65, None])
def test_validate_name_rejects(s):
    with pytest.raises(token_db.ValidationError):
        token_db.validate_name(s)


@pytest.mark.parametrize("d", [30, 90, 365])
def test_validate_expires_in_days_accepts_allowed(d):
    assert token_db.validate_expires_in_days(d) == d


@pytest.mark.parametrize("d", [0, -1, 7, 31, 366, "90", None])
def test_validate_expires_in_days_rejects_others(d):
    with pytest.raises(token_db.ValidationError):
        token_db.validate_expires_in_days(d)
