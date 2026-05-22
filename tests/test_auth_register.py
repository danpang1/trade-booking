"""Pure-logic unit tests for auth_register validation helpers (delegated to user_db).
The script itself is exercised by smoke_auth.py against a real UAT DB.
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import pytest  # noqa: E402
import user_db  # noqa: E402


@pytest.mark.parametrize("pw", ["", "short", "1234567"])
def test_validate_password_rejects_too_short(pw):
    with pytest.raises(user_db.ValidationError):
        user_db.validate_password(pw)


def test_validate_password_accepts_ok():
    assert user_db.validate_password("Secret-123") == "Secret-123"


def test_registration_payload_path():
    """The registration script reuses user_db validators; sanity-check the chain."""
    user_db.validate_username("new_user")
    user_db.validate_email("new@example.com")
    user_db.validate_password("Secret-123")
