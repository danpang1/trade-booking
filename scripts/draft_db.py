"""Shared helper for draft_* endpoint scripts.

Pure-logic functions (validate_category, validate_uuid, validate_payload_for_category,
row_to_public) live here and are exercised by tests/test_draft_db.py without
touching the DB. DB-touching functions reuse cashflow_db.connect.
"""
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
import re as _re
import sys as _sys
import uuid as _uuid

import cashflow_db
import spot_db


# ── Constants ──────────────────────────────────────────────────────

CATEGORIES = ("CASHFLOW", "SPOT")
STATUSES = ("PENDING_REVIEW", "APPROVED", "REJECTED")
SOURCES = ("CLAUDE_CODE",)


class ValidationError(ValueError):
    """Raised by validate_* helpers; caught in main() and rendered as JSON."""


# ── Validators ─────────────────────────────────────────────────────

def validate_category(c) -> str:
    if not isinstance(c, str) or c not in CATEGORIES:
        raise ValidationError(f"category must be one of {CATEGORIES}, got {c!r}")
    return c


def validate_uuid(s) -> str:
    if not isinstance(s, str) or not s:
        raise ValidationError("uuid must be a non-empty string")
    try:
        _uuid.UUID(s)
    except (ValueError, AttributeError, TypeError) as e:
        raise ValidationError(f"invalid uuid: {s!r}") from e
    return s


def validate_payload_for_category(category: str, payload) -> None:
    """Delegate to the relevant *_db validator (insert mode)."""
    if category == "CASHFLOW":
        try:
            cashflow_db.validate_payload(payload, mode="insert")
        except cashflow_db.ValidationError as e:
            raise ValidationError(str(e)) from e
        return
    if category == "SPOT":
        try:
            spot_db.validate_payload(payload, mode="insert")
        except spot_db.ValidationError as e:
            raise ValidationError(str(e)) from e
        return
    raise ValidationError(f"unknown category: {category!r}")


# ── On-behalf-of booking ───────────────────────────────────────────

# Who a draft is booked BY is normally the authenticated caller. A service
# caller such as the Colossus Slack bot books for many people through one
# API token; it names the real requester in `requested_by`, and that name
# becomes the draft's user_id while `created_by` keeps the token owner as
# the audit trail. Only a Bearer session may do this: a cookie session is a
# person at the form, and there is no honest reason for them to book as
# someone else.
REQUESTED_BY_RE = _re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def lookup_active_user(username: str):
    """The canonical username of an active MO user with TMS access, else None."""
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT username FROM users "
                " WHERE LOWER(username) = LOWER(%s) "
                "   AND status = 'active' AND access_tms",
                (username,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def resolve_booker(payload, acting: str, auth_mode, lookup=None) -> tuple[str, dict]:
    """(username to stamp as the booker, payload without `requested_by`).

    Raises ValidationError when `requested_by` is present on a non-Bearer
    session, is malformed, or names no active MO user.
    """
    if not isinstance(payload, dict) or "requested_by" not in payload:
        return acting, payload
    payload = dict(payload)
    requested = payload.pop("requested_by")
    if requested in (None, ""):
        return acting, payload
    if auth_mode != "bearer":
        raise ValidationError("requested_by is only accepted from API-token callers")
    if not isinstance(requested, str) or not REQUESTED_BY_RE.match(requested):
        raise ValidationError(f"invalid requested_by: {requested!r}")
    found = (lookup or lookup_active_user)(requested)
    if not found:
        raise ValidationError(
            f"requested_by {requested!r} is not an active MO user with TMS access")
    print(f"draft booked on behalf of {found} via token of {acting}", file=_sys.stderr)
    return found, payload


# ── DB-touching ────────────────────────────────────────────────────

def connect():
    """Reuse the MO_DB_UAT connection used by cashflow scripts."""
    return cashflow_db.connect()


# Columns returned to the API consumer. (Drafts have no secrets, but we
# keep the mapping centralized so date isoformat is consistent.)
PUBLIC_COLUMNS = (
    "id", "category", "payload", "status", "batch_id",
    "client_request_id", "created_by", "created_at", "updated_at",
    "approved_at", "approved_by", "approved_deal_ref",
    "rejected_at", "rejected_by", "rejection_reason",
)


def _json_safe(v):
    if isinstance(v, Decimal):
        return format(v.normalize(), "f") if v == v.to_integral_value() else str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, _uuid.UUID):
        return str(v)
    return v


def row_to_public(cur, row) -> dict:
    """Map a SELECT-* row to the API JSON payload."""
    cols = [d.name for d in cur.description]
    return {
        c: _json_safe(v)
        for c, v in zip(cols, row)
        if c in PUBLIC_COLUMNS
    }
