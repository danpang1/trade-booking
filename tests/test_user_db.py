"""Pure-logic unit tests for user_db. No DB connection required."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pytest  # noqa: E402  (must follow sys.path.insert above)
import user_db  # noqa: E402


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


def test_count_admins_returns_integer_from_cursor():
    """Locks in the SQL string + return type. count_admins is the single
    load-bearing function for both the last-admin demote guard
    (user_update.py) and the last-admin delete guard (user_delete.py).
    If this function ever stops returning an int, both guards silently
    fail open."""
    captured = {}

    class _StubCur:
        def execute(self, sql, *args):
            captured["sql"] = sql

        def fetchone(self):
            return (3,)  # the DB says there are 3 admins

    assert user_db.count_admins(_StubCur()) == 3
    assert "role='admin'" in captured["sql"]
    assert "SELECT COUNT(*)" in captured["sql"].upper()


def test_row_to_public_never_leaks_password_hash():
    """Locks in PUBLIC_COLUMNS whitelist: even if a SELECT returns password_hash,
    row_to_public must drop it. This is the single security invariant of user_db."""
    class _StubCol:
        def __init__(self, name):
            self.name = name

    class _StubCur:
        description = [_StubCol(n) for n in
                       ("id", "username", "email", "role",
                        "password_hash", "created_at", "updated_at")]

    row = (1, "peter", "peter@x.com", "admin",
           "$2b$12$THIS_IS_THE_SECRET_HASH_AND_MUST_NOT_LEAK..............",
           None, None)
    out = user_db.row_to_public(_StubCur(), row)

    assert "password_hash" not in out
    assert out["username"] == "peter"
    assert out["role"] == "admin"
    assert set(out.keys()) == set(user_db.PUBLIC_COLUMNS)
