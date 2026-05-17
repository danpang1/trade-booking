"""Shared helper for loan_insert/amend/recent/get/history scripts.

Pure logic (validation, (de)serialization) lives here for unit testing.
DB-touching scripts call into here for creds + connection. Mirrors
cashflow_db.py — kept separate so the loan-specific column list,
required-fields tuple, and CHECK-constraint mirrors don't pollute the
cashflow path.
"""
from __future__ import annotations
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENV = REPO / ".env"


def load_creds() -> dict[str, str]:
    """Parse the #MO DB UAT block from <repo>/.env. Same convention as
    cashflow_db.load_creds — kept duplicate (not imported) so loan_*
    scripts have no implicit dependency on the cashflow module."""
    if not ENV.exists():
        raise FileNotFoundError(f".env not found at {ENV}")

    creds: dict[str, str] = {}
    in_block = False
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if "MO DB UAT" in s.upper():
            in_block = True
            continue
        if not in_block:
            continue
        if not s or s.startswith("#"):
            if s.startswith("#") and "MO DB UAT" not in s.upper():
                break
            continue
        if ":" in s:
            k, _, v = s.partition(":")
            key = k.strip().lower()
            if key.startswith("mo_db_"):
                key = key[len("mo_db_"):]
            creds[key] = v.strip()

    if not creds:
        raise RuntimeError(
            f"No '# MO DB UAT' block (or empty block) found in {ENV}"
        )
    return creds


def connect():
    """Open a psycopg2 connection. Caller manages txns (autocommit=False).
    Pins session TZ to UTC so TIMESTAMPTZ values render with +00 offset."""
    import psycopg2
    c = load_creds()
    conn = psycopg2.connect(
        host=c["host"],
        port=int(c.get("port", "5432")),
        dbname=c["database"],
        user=c["username"],
        password=c["password"],
        connect_timeout=15,
    )
    with conn.cursor() as cur:
        cur.execute("SET TIMEZONE = 'UTC'")
    conn.commit()
    return conn


REQUIRED_FIELDS_INSERT = (
    "direction", "loan_type", "entity", "portfolio_id", "portfolio_name",
    "principal_asset", "principal_amount", "interest_asset",
    "interest_type", "trade_date", "user_id", "status",
)
REQUIRED_FIELDS_AMEND = REQUIRED_FIELDS_INSERT + ("deal_ref",)

VALID_DIRECTIONS = {"BORROW", "LEND"}
VALID_LOAN_TYPES = {"VIP LOAN", "INTERNAL", "EXTERNAL", "DEFI LENDING"}
VALID_INTEREST_TYPES = {"FIXED", "FLOATING"}
VALID_DAY_COUNT_BASIS = {360, 365}
VALID_STATUSES = {"LIVE", "MATURED", "CANCELLED"}


class ValidationError(ValueError):
    """Payload failed pre-DB validation. Raised before opening a txn."""


def _validate_one(p: dict, mode: str) -> None:
    required = REQUIRED_FIELDS_AMEND if mode == "amend" else REQUIRED_FIELDS_INSERT
    for f in required:
        v = p.get(f)
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValidationError(f"required field missing or empty: {f}")

    if p["direction"] not in VALID_DIRECTIONS:
        raise ValidationError(
            f"direction must be one of {sorted(VALID_DIRECTIONS)}, got {p['direction']!r}"
        )
    if p["loan_type"] not in VALID_LOAN_TYPES:
        raise ValidationError(
            f"loan_type must be one of {sorted(VALID_LOAN_TYPES)}, got {p['loan_type']!r}"
        )
    if p["interest_type"] not in VALID_INTEREST_TYPES:
        raise ValidationError(
            f"interest_type must be one of {sorted(VALID_INTEREST_TYPES)}, got {p['interest_type']!r}"
        )
    # day_count_basis is optional in the payload — falls back to 365
    # at write time. When supplied it must be exactly 360 or 365.
    if "day_count_basis" in p and p["day_count_basis"] not in (None, "", 365, "365", 360, "360"):
        try:
            dcb = int(p["day_count_basis"])
        except (TypeError, ValueError) as e:
            raise ValidationError(
                f"day_count_basis must be 360 or 365, got {p['day_count_basis']!r}"
            ) from e
        if dcb not in VALID_DAY_COUNT_BASIS:
            raise ValidationError(
                f"day_count_basis must be 360 or 365, got {dcb}"
            )
    if p["status"] not in VALID_STATUSES:
        raise ValidationError(
            f"status must be one of {sorted(VALID_STATUSES)}, got {p['status']!r}"
        )

    try:
        pa = Decimal(str(p["principal_amount"]))
    except (InvalidOperation, TypeError, ValueError) as e:
        raise ValidationError(
            f"principal_amount must be numeric, got {p['principal_amount']!r}"
        ) from e
    if pa <= 0:
        raise ValidationError("principal_amount must be > 0")

    if p.get("interest_rate_pa_pct") not in (None, "", 0):
        try:
            Decimal(str(p["interest_rate_pa_pct"]))
        except (InvalidOperation, TypeError, ValueError) as e:
            raise ValidationError(
                f"interest_rate_pa_pct must be numeric if set, got {p['interest_rate_pa_pct']!r}"
            ) from e

    try:
        int(p["portfolio_id"])
    except (TypeError, ValueError) as e:
        raise ValidationError(
            f"portfolio_id must be integer, got {p['portfolio_id']!r}"
        ) from e

    # Mirror trades_loan_collateral_pair CHECK so we fail fast with a
    # readable message instead of a DB constraint error.
    ca, camt = p.get("collateral_asset"), p.get("collateral_amount")
    has_asset = bool(ca) and (not isinstance(ca, str) or bool(ca.strip()))
    has_amt = camt not in (None, "") and str(camt).strip() not in ("", "0")
    if has_asset != has_amt:
        raise ValidationError(
            "collateral_asset and collateral_amount must both be set or both null"
        )
    if has_amt:
        try:
            d = Decimal(str(camt))
        except (InvalidOperation, TypeError, ValueError) as e:
            raise ValidationError(
                f"collateral_amount must be numeric, got {camt!r}"
            ) from e
        if d <= 0:
            raise ValidationError("collateral_amount must be > 0 when set")

    # Mirror trades_loan_hedge_consistency CHECK.
    if p.get("is_hedged"):
        for f in ("hedged_asset", "hedged_qty", "hedged_price"):
            if not p.get(f):
                raise ValidationError(f"{f} is required when is_hedged=true")
        for f in ("hedged_qty", "hedged_price"):
            try:
                d = Decimal(str(p[f]))
            except (InvalidOperation, TypeError, ValueError) as e:
                raise ValidationError(f"{f} must be numeric, got {p[f]!r}") from e
            if d <= 0:
                raise ValidationError(f"{f} must be > 0 when is_hedged=true")

    # Mirror trades_loan_floating_benchmark_consistency: benchmark only set when FLOATING.
    if p["interest_type"] != "FLOATING" and p.get("floating_benchmark"):
        raise ValidationError(
            "floating_benchmark must be null unless interest_type='FLOATING'"
        )


def validate_payload(payload, *, mode: str) -> None:
    """Raise ValidationError if payload is bad. mode in {'insert', 'amend'}.
    Loan doesn't have a mirror-leg concept (each loan contract is one
    row), so list payloads are rejected."""
    if mode not in ("insert", "amend"):
        raise ValidationError(f"unknown mode: {mode}")
    if isinstance(payload, list):
        raise ValidationError("loan payload must be a single object, not a list")
    if not isinstance(payload, dict):
        raise ValidationError(f"payload must be dict, got {type(payload).__name__}")
    _validate_one(payload, mode)


# Column order matches apply_schema_loan.py DDL declaration.
# effective_start / effective_end are populated by SQL expressions in the
# INSERT statement, not by these tuples.
DATA_COLUMNS = (
    "deal_ref",
    "order_id",
    "txn_type",
    "direction",
    "loan_type",
    "entity",
    "portfolio_id",
    "portfolio_name",
    "counterparty_id",
    "counterparty",
    "principal_asset",
    "principal_amount",
    "interest_asset",
    "interest_rate_pa_pct",
    "interest_type",
    "day_count_basis",
    "floating_benchmark",
    "collateral_asset",
    "collateral_amount",
    "is_hedged",
    "hedged_asset",
    "hedged_qty",
    "hedged_price",
    "hedge_proceeds_asset",
    "hedge_proceeds_amount",
    "trade_date",
    "maturity_date",
    "user_id",
    "status",
    "comment",
)


def _coerce_str_or_none(v):
    if v is None:
        return None
    if isinstance(v, str) and not v.strip():
        return None
    return v


def payload_to_columns(payload: dict, *, deal_ref: str) -> tuple[tuple[str, ...], tuple]:
    """Convert form JSON to (column_names, values) tuples for INSERT.

    deal_ref is passed in (allocated from trade_seq_loan on insert,
    preserved on amend) — never trusted from the frontend on insert.
    """
    vals = []
    for col in DATA_COLUMNS:
        if col == "deal_ref":
            vals.append(deal_ref)
        elif col == "txn_type":
            vals.append("LOAN")
        elif col == "portfolio_id":
            vals.append(str(payload["portfolio_id"]).strip())
        elif col == "is_hedged":
            vals.append(bool(payload.get("is_hedged")))
        elif col == "interest_rate_pa_pct":
            v = payload.get("interest_rate_pa_pct")
            vals.append("0" if v in (None, "") else v)
        elif col == "day_count_basis":
            v = payload.get("day_count_basis")
            # Fall back to 365 (Actual/365) when the frontend omits the
            # field — keeps amend payloads from older clients valid.
            vals.append(365 if v in (None, "") else int(v))
        elif col in ("principal_amount", "collateral_amount", "hedged_qty",
                     "hedged_price", "hedge_proceeds_amount"):
            v = payload.get(col)
            vals.append(None if v in (None, "") else v)
        else:
            vals.append(_coerce_str_or_none(payload.get(col)))
    return DATA_COLUMNS, tuple(vals)


def _json_safe(v):
    if isinstance(v, Decimal):
        return format(v.normalize(), "f") if v == v.to_integral_value() else str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def row_to_payload(columns, row) -> dict:
    """psycopg2 row tuple → JSON-safe dict keyed by column name."""
    return {col: _json_safe(val) for col, val in zip(columns, row)}
