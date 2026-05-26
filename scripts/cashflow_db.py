"""Shared helper for cashflow_insert/amend/recent/get scripts.

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

    Pins the session timezone to UTC so all TIMESTAMPTZ values
    (effective_start, effective_end, trade_date, value_date) render
    with a +00 offset regardless of any future role/database default
    change. Redundant with the ALTER ROLE mo_admin SET timezone='UTC'
    we set on the server, but cheap and explicit.
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
    conn.commit()  # SET TIMEZONE is a session command; commit closes the implicit txn
    return conn


REQUIRED_FIELDS_INSERT = (
    "cashflow_type", "direction", "entity", "portfolio_id",
    "portfolio_name", "counterparty", "account", "asset", "amount",
    "trade_date", "value_date", "user_id", "status",
)
REQUIRED_FIELDS_AMEND = REQUIRED_FIELDS_INSERT + ("deal_ref",)

VALID_DIRECTIONS = {"INCOMING", "OUTGOING"}
VALID_STATUSES = {"PENDING", "CONFIRMED", "PROCESSED", "SETTLED", "CANCELLED"}
# Mirrors the CASHFLOW_TYPES placeholder list in src/TradeBookingForm.jsx
# (line ~219). Backend will swap to MySQL select_category=CASHFLOW TYPE
# (28 values) eventually; until then this set is the single source of
# truth so Claude / future plugins / direct form bookings all see the
# same 400 when a non-standard type leaks through.
VALID_CASHFLOW_TYPES = {
    "INTER PTF FUNDING", "RETAINER FEES", "OPEX",
    "OTHER INCOME", "OTHER EXPENSE", "TRANSFER FEES",
    "INTEREST EXPENSE", "INTEREST INCOME", "WITHHOLDING TAX",
    "LOAN", "LOAN REPAYMENT",
}


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
    if p["cashflow_type"] not in VALID_CASHFLOW_TYPES:
        raise ValidationError(
            f"cashflow_type must be one of {sorted(VALID_CASHFLOW_TYPES)}, "
            f"got {p['cashflow_type']!r}"
        )
    try:
        amount_dec = Decimal(str(p["amount"]))
    except (InvalidOperation, TypeError, ValueError) as e:
        raise ValidationError(f"amount must be numeric, got {p['amount']!r}") from e
    # Mirrors the form's "Notional amount must be > 0" rule (the form
    # stores cf_amount as a positive magnitude with direction separate;
    # the payload's amount carries the sign). Zero is a no-op booking.
    if abs(amount_dec) == 0:
        raise ValidationError(
            f"amount must be non-zero, got {p['amount']!r}"
        )
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
    "counterparty_id",
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
            # Stored as TEXT so DB clients render it without thousands
            # separators. Coerced from whatever the frontend sends (int
            # or string); validate_payload still confirms it's numeric.
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
    Caller passes the column list (e.g., from cursor.description or known SELECT order).
    """
    return {col: _json_safe(val) for col, val in zip(columns, row)}
