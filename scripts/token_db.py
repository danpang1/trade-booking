"""Shared helper for token_*/auth_whoami_bearer scripts.

Pure-logic functions (generate_token, hash_token, validators) live here
and are exercised by tests/test_token_db.py without touching the DB.
DB-touching functions reuse cashflow_db.connect.
"""
from __future__ import annotations
import hashlib
import secrets

import cashflow_db  # reuse Postgres creds + connect


# ── Pure logic ────────────────────────────────────────────────────

TOKEN_PREFIX_STR = "tkmo_"
TOKEN_RANDOM_BYTES = 32      # → 43-char url-safe base64 string
TOKEN_TOTAL_LEN = 5 + 43     # "tkmo_" + 43 random chars
TOKEN_PREFIX_LEN = 16        # what we store/display
MAX_NAME_LEN = 64
ALLOWED_EXPIRES_DAYS = (30, 90, 365)


class ValidationError(ValueError):
    """Raised by validate_* helpers; caught in main() and rendered as JSON."""


def generate_token() -> str:
    """Generate a new plaintext token: 'tkmo_' + 43 url-safe random chars."""
    return TOKEN_PREFIX_STR + secrets.token_urlsafe(TOKEN_RANDOM_BYTES)


def hash_token(plaintext: str) -> str:
    """sha256 hex of the plaintext. 64 chars."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def token_prefix(plaintext: str) -> str:
    """First 16 chars of plaintext — displayed to users to identify the token."""
    return plaintext[:TOKEN_PREFIX_LEN]


def validate_name(s) -> str:
    if not isinstance(s, str):
        raise ValidationError("name must be a string")
    s2 = s.strip()
    if not s2:
        raise ValidationError("name must be non-empty")
    if len(s2) > MAX_NAME_LEN:
        raise ValidationError(f"name must be <= {MAX_NAME_LEN} chars")
    return s2


def validate_expires_in_days(d) -> int:
    if not isinstance(d, int) or isinstance(d, bool):
        raise ValidationError(f"expires_in_days must be int in {ALLOWED_EXPIRES_DAYS}")
    if d not in ALLOWED_EXPIRES_DAYS:
        raise ValidationError(f"expires_in_days must be one of {ALLOWED_EXPIRES_DAYS}")
    return d


# ── DB-touching ───────────────────────────────────────────────────

def connect():
    """Reuse the MO_DB_UAT connection used by cashflow scripts."""
    return cashflow_db.connect()


# Columns returned to the API consumer. token_hash NEVER appears here.
PUBLIC_COLUMNS = (
    "id", "token_prefix", "name",
    "created_at", "last_used_at", "expires_at", "revoked_at",
)


def row_to_public(cur, row) -> dict:
    """Map a SELECT-* row to the public payload (omits token_hash)."""
    cols = [d.name for d in cur.description]
    out = {c: v for c, v in zip(cols, row) if c in PUBLIC_COLUMNS}
    for k in ("created_at", "last_used_at", "expires_at", "revoked_at"):
        if out.get(k) is not None:
            out[k] = out[k].isoformat()
    return out
