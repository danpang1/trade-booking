"""Pure-logic unit tests for user_db. No DB connection required."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pytest
import user_db


def test_hash_then_verify_round_trip():
    h = user_db.hash_password("CorrectHorse9!")
    assert len(h) == 60
    assert user_db.verify_password("CorrectHorse9!", h)
    assert not user_db.verify_password("wrong", h)


def test_verify_password_handles_garbage_hash():
    assert user_db.verify_password("anything", "not-a-real-hash") is False
    assert user_db.verify_password("anything", "") is False


@pytest.mark.parametrize("s", ["pe", "ab", ""])
def test_validate_username_rejects_too_short(s):
    with pytest.raises(user_db.ValidationError):
        user_db.validate_username(s)


@pytest.mark.parametrize("s", ["peter", "peter.pang", "peter_p-1"])
def test_validate_username_accepts_good_chars(s):
    assert user_db.validate_username(s) == s


@pytest.mark.parametrize("s", ["peter pang", "peter@x", "peter!"])
def test_validate_username_rejects_bad_chars(s):
    with pytest.raises(user_db.ValidationError):
        user_db.validate_username(s)


def test_validate_email_basic():
    assert user_db.validate_email("a@b.c") == "a@b.c"
    with pytest.raises(user_db.ValidationError):
        user_db.validate_email("not-an-email")
    with pytest.raises(user_db.ValidationError):
        user_db.validate_email("no-domain@")


def test_validate_role():
    assert user_db.validate_role("admin") == "admin"
    assert user_db.validate_role("user") == "user"
    with pytest.raises(user_db.ValidationError):
        user_db.validate_role("superadmin")


def test_validate_password_min_length():
    user_db.validate_password("12345678")
    with pytest.raises(user_db.ValidationError):
        user_db.validate_password("short")
