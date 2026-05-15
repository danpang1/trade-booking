"""Shared helper for cashflow_insert/amend/recent/get scripts.

Pure logic (validation, (de)serialization) lives here for unit testing.
DB-touching scripts call into here for creds + connection.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENV = REPO / ".env"


def load_creds() -> dict[str, str]:
    """Parse the #MO DB UAT block from <repo>/.env.

    Same convention as apply_schema_cashflow.py — block starts at the
    `# MO DB UAT` marker and ends at the next `#` comment that isn't the
    marker or at EOF.

    Keys are lowercased and any `mo_db_` prefix is stripped, so both
    ``MO_DB_HOST: ...`` (production format) and ``host: ...`` (unprefixed)
    produce the same normalized dict.
    """
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
    """Open a psycopg2 connection. Caller manages txns (autocommit=False)."""
    import psycopg2  # imported here so pure-logic functions are testable without psycopg2
    c = load_creds()
    return psycopg2.connect(
        host=c["host"],
        port=int(c.get("port", "5432")),
        dbname=c["database"],
        user=c["username"],
        password=c["password"],
        connect_timeout=15,
    )


REQUIRED_FIELDS_INSERT = (
    "cashflow_type", "direction", "entity", "portfolio_id",
    "portfolio_name", "asset", "amount", "trade_date", "value_date",
    "user_id", "status",
)
REQUIRED_FIELDS_AMEND = REQUIRED_FIELDS_INSERT + ("deal_ref",)

VALID_DIRECTIONS = {"RECEIVE", "PAY"}
VALID_STATUSES = {"PENDING", "CONFIRMED", "PROCESSED", "SETTLED", "CANCELLED"}


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
    if p["status"] not in VALID_STATUSES:
        raise ValidationError(
            f"status must be one of {sorted(VALID_STATUSES)}, got {p['status']!r}"
        )
    try:
        Decimal(str(p["amount"]))
    except (InvalidOperation, TypeError, ValueError) as e:
        raise ValidationError(f"amount must be numeric, got {p['amount']!r}") from e
    if p.get("fee_amount") not in (None, "", 0):
        try:
            Decimal(str(p["fee_amount"]))
        except (InvalidOperation, TypeError, ValueError) as e:
            raise ValidationError(
                f"fee_amount must be numeric if set, got {p['fee_amount']!r}"
            ) from e
    try:
        int(p["portfolio_id"])
    except (TypeError, ValueError) as e:
        raise ValidationError(
            f"portfolio_id must be integer, got {p['portfolio_id']!r}"
        ) from e


def validate_payload(payload, *, mode: str) -> None:
    """Raise ValidationError if payload is bad. mode in {'insert', 'amend'}.

    On insert the payload may be a 2-element list (mirror-leg). On amend
    only a single dict is supported (mirror legs are independent deal_refs).
    """
    if mode not in ("insert", "amend"):
        raise ValidationError(f"unknown mode: {mode}")
    if isinstance(payload, list):
        if mode != "insert":
            raise ValidationError("mirror-leg list only supported on insert mode")
        if len(payload) != 2:
            raise ValidationError(
                f"mirror-leg payload must have exactly 2 elements, got {len(payload)}"
            )
        for leg in payload:
            _validate_one(leg, mode)
        return
    if not isinstance(payload, dict):
        raise ValidationError(f"payload must be dict or 2-element list, got {type(payload).__name__}")
    _validate_one(payload, mode)


# Column order matches apply_schema_cashflow.py DDL declaration.
# effective_start / effective_end are populated by SQL expressions in the
# INSERT statement (NOW() and NULL respectively), not by these tuples.
DATA_COLUMNS = (
    "deal_ref",
    "external_trade_id",
    "txn_type",
    "cashflow_type",
    "direction",
    "entity",
    "portfolio_id",
    "portfolio_name",
    "counterparty",
    "account",
    "account_type",
    "asset",
    "amount",
    "fee_asset",
    "fee_amount",
    "trade_date",
    "value_date",
    "network",
    "txid_reference",
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

    `deal_ref` is passed in (allocated from trade_seq_cashflow on insert,
    preserved from the payload on amend) — it isn't trusted from the
    frontend on insert.
    """
    vals = []
    for col in DATA_COLUMNS:
        if col == "deal_ref":
            vals.append(deal_ref)
        elif col == "txn_type":
            vals.append("CASHFLOW")
        elif col == "portfolio_id":
            vals.append(int(payload["portfolio_id"]))
        elif col == "fee_amount":
            v = payload.get("fee_amount")
            vals.append("0" if v in (None, "") else v)
        else:
            vals.append(_coerce_str_or_none(payload.get(col)))
    return DATA_COLUMNS, tuple(vals)
