"""Helpers for the funding_settings key-value table.

fetch_settings(): read all known keys, filling defaults for absent rows.
upsert_setting(): write-or-overwrite one key's value.

Keys are a fixed allowlist so the Dashboard band and the store stay in
lockstep. Values are plain numbers (ITD PnL may be negative).
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation


class FundingSettingError(ValueError):
    pass


# Allowlisted keys and their fallback values when no row exists yet.
DEFAULTS = {
    "capital": 6_600_000.0,
    "itd_pnl": 0.0,
}


def _coerce_number(value) -> float:
    try:
        num = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError, ValueError):
        raise FundingSettingError(f"value is not a number: {value!r}")
    if not num.is_finite():
        raise FundingSettingError(f"value is not finite: {value!r}")
    return float(num)


def fetch_settings(cur) -> dict:
    """Return {key: float} for every allowlisted key, using DEFAULTS for
    any key without a stored row."""
    out = dict(DEFAULTS)
    cur.execute("SELECT key, value FROM funding_settings")
    for row in cur.fetchall():
        key = row[0]
        if key in out:
            out[key] = float(row[1])
    return out


def upsert_setting(cur, key: str, value, user_id: str) -> dict:
    """Insert or overwrite one setting. Keyed by `key`."""
    key = (key or "").strip()
    if key not in DEFAULTS:
        raise FundingSettingError(f"unknown setting key: {key!r}")
    if not user_id or not user_id.strip():
        raise FundingSettingError("user_id is required")
    num = _coerce_number(value)
    cur.execute(
        """
        INSERT INTO funding_settings (key, value, updated_at, updated_by)
        VALUES (%s, %s, NOW(), %s)
        ON CONFLICT (key) DO UPDATE
          SET value      = EXCLUDED.value,
              updated_at = NOW(),
              updated_by = EXCLUDED.updated_by
        RETURNING key, value, updated_at, updated_by
        """,
        (key, num, user_id.strip()),
    )
    row = cur.fetchone()
    return {
        "key": row[0],
        "value": float(row[1]),
        "updated_at": row[2].isoformat() if row[2] else None,
        "updated_by": row[3],
    }
