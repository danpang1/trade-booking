"""Shared helper for user_*/auth_* scripts.

Pure-logic functions (hash_password, verify_password, validators) live here
and are exercised by tests/test_user_db.py without touching the DB.
DB-touching functions reuse cashflow_db.load_creds / connect.
"""
from __future__ import annotations
import re

import bcrypt

import cashflow_db  # reuse Postgres creds + connect


# ── Pure logic ────────────────────────────────────────────────────

USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,64}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ROLES = ("admin", "user")
MIN_PW_LEN = 8


class ValidationError(ValueError):
    """Raised by validate_* helpers; caught in main() and rendered as JSON."""


def hash_password(plain: str) -> str:
    """bcrypt cost 12 → exactly 60-char hash."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def validate_username(s: str) -> str:
    if not isinstance(s, str) or not USERNAME_RE.match(s):
        raise ValidationError("username must be 3-64 chars [a-zA-Z0-9._-]")
    return s


def validate_email(s: str) -> str:
    if not isinstance(s, str) or not EMAIL_RE.match(s):
        raise ValidationError("invalid email")
    return s


def validate_role(s: str) -> str:
    if s not in ROLES:
        raise ValidationError(f"role must be one of {ROLES}")
    return s


def validate_password(s: str) -> str:
    if not isinstance(s, str) or len(s) < MIN_PW_LEN:
        raise ValidationError(f"password must be >= {MIN_PW_LEN} chars")
    return s


# ── DB-touching ───────────────────────────────────────────────────

def connect():
    """Reuse the MO_DB_UAT connection used by cashflow scripts."""
    return cashflow_db.connect()


# Columns returned to the API consumer. password_hash NEVER appears here.
PUBLIC_COLUMNS = ("id", "username", "email", "role", "created_at", "updated_at")


def row_to_public(cur, row) -> dict:
    """Map a SELECT-* row to the public payload (omits password_hash)."""
    cols = [d.name for d in cur.description]
    record = dict(zip(cols, row))
    out = {}
    for k in PUBLIC_COLUMNS:
        v = record.get(k)
        if hasattr(v, "isoformat"):
            v = v.isoformat()
        out[k] = v
    return out


def count_admins(cur) -> int:
    cur.execute("SELECT COUNT(*) FROM users WHERE role='admin'")
    return int(cur.fetchone()[0])
