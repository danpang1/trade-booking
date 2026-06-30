"""Shared helper for draft_* endpoint scripts.

Pure-logic functions (validate_category, validate_uuid, validate_payload_for_category,
row_to_public) live here and are exercised by tests/test_draft_db.py without
touching the DB. DB-touching functions reuse cashflow_db.connect.
"""
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
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
