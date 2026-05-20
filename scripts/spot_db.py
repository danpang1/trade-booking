"""Shared helper for spot_insert/amend/recent/get scripts.

Pure logic (validation, (de)serialization) lives here for unit testing.
DB-touching scripts call into here for creds + connection.
"""
from __future__ import annotations
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENV = REPO / ".env"


def load_creds() -> dict[str, str]:
    """Load Postgres UAT creds, env vars taking precedence over .env file.

    Env vars (used in k8s): MO_DB_HOST, MO_DB_PORT, MO_DB_DATABASE,
    MO_DB_USERNAME, MO_DB_PASSWORD. If all five (or four — port defaults
    to 5432) are present, the .env file is not read at all.

    .env fallback (used in local dev): parses the `# MO DB UAT` block.
    Block starts at the marker, ends at the next `#` comment that isn't the
    marker or at EOF. Keys are lowercased and any `mo_db_` prefix is stripped,
    so both ``MO_DB_HOST: ...`` and ``host: ...`` produce the same dict.
    """
    env_creds = {
        k: os.environ[f"MO_DB_{k.upper()}"]
        for k in ("host", "port", "database", "username", "password")
        if f"MO_DB_{k.upper()}" in os.environ
    }
    if all(k in env_creds for k in ("host", "database", "username", "password")):
        env_creds.setdefault("port", "5432")
        return env_creds

    if not ENV.exists():
        raise FileNotFoundError(
            f".env not found at {ENV} and MO_DB_* env vars are incomplete"
        )

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

    Pins the session timezone to UTC so all TIMESTAMPTZ values render
    with a +00 offset regardless of any future role/database default.
    """
    import psycopg2  # imported here so pure-logic functions are testable without psycopg2
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
    "direction", "entity", "portfolio_id", "portfolio_name",
    "base_asset", "base_amount", "quote_asset", "quote_amount", "price",
    "trade_date", "value_date", "user_id", "status",
)
REQUIRED_FIELDS_AMEND = REQUIRED_FIELDS_INSERT + ("deal_ref",)

VALID_DIRECTIONS = {"LONG", "SHORT"}
VALID_STATUSES = {"PENDING", "CONFIRMED", "PROCESSED", "SETTLED", "CANCELLED"}


class ValidationError(ValueError):
    """Payload failed pre-DB validation. Raised before opening a txn."""


def _validate_numeric(p: dict, field: str) -> None:
    try:
        Decimal(str(p[field]))
    except (InvalidOperation, TypeError, ValueError) as e:
        raise ValidationError(f"{field} must be numeric, got {p[field]!r}") from e


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
    for f in ("base_amount", "quote_amount", "price"):
        _validate_numeric(p, f)
    if p.get("fee_amount") not in (None, "", 0):
        _validate_numeric(p, "fee_amount")
    if p["base_asset"] == p["quote_asset"]:
        raise ValidationError(
            f"base_asset and quote_asset must differ, both = {p['base_asset']!r}"
        )
    try:
        int(p["portfolio_id"])
    except (TypeError, ValueError) as e:
        raise ValidationError(
            f"portfolio_id must be integer, got {p['portfolio_id']!r}"
        ) from e


def validate_payload(payload, *, mode: str) -> None:
    """Raise ValidationError if payload is bad. mode in {'insert', 'amend'}.

    SPOT has no mirror-leg construct (single record per side of the trade),
    so the payload is always a single dict — list-shaped payloads are rejected.
    """
    if mode not in ("insert", "amend"):
        raise ValidationError(f"unknown mode: {mode}")
    if isinstance(payload, list):
        raise ValidationError("SPOT payload must be a single dict, not a list")
    if not isinstance(payload, dict):
        raise ValidationError(f"payload must be dict, got {type(payload).__name__}")
    _validate_one(payload, mode)


# Column order matches apply_schema_spot.py DDL declaration, minus
# effective_start / effective_end (set by SQL expressions NOW() / NULL in
# the INSERT statement, not by these tuples).
DATA_COLUMNS = (
    "deal_ref",
    "external_trade_id",
    "txn_type",
    "direction",
    "entity",
    "portfolio_id",
    "portfolio_name",
    "counterparty",
    "counterparty_id",
    "account",
    "account_type",
    "base_asset",
    "base_amount",
    "quote_asset",
    "quote_amount",
    "price",
    "fee_asset",
    "fee_amount",
    "trade_date",
    "value_date",
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

    `deal_ref` is passed in (allocated from trade_seq_spot on insert,
    preserved from the payload on amend) — it isn't trusted from the
    frontend on insert.
    """
    vals = []
    for col in DATA_COLUMNS:
        if col == "deal_ref":
            vals.append(deal_ref)
        elif col == "txn_type":
            vals.append("SPOT")
        elif col == "portfolio_id":
            # Stored as TEXT so DB clients render it without thousands
            # separators. Coerced from whatever the frontend sends.
            vals.append(str(payload["portfolio_id"]).strip())
        elif col == "fee_amount":
            v = payload.get("fee_amount")
            vals.append("0" if v in (None, "") else v)
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
    """Convert a psycopg2 row tuple to a JSON-safe dict keyed by column name.

    Decimal → string (preserves precision for amounts), datetime → ISO 8601.
    """
    return {col: _json_safe(val) for col, val in zip(columns, row)}
