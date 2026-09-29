"""Shared helper for transfer_insert/amend/recent/get/history scripts.

trades_transfer holds MOVEMENTS of an asset: one row per transfer with
both ends on it. A transfer changes where a position sits, never P&L; the
P&L engine reads trades_cashflow and never this table, so "transfers do
not affect P&L" is a property of where the row lives.

  INTERNAL  both ends are our accounts. Booked OUTGOING from the source's
            point of view, amount negative: the source loses |amount|, the
            destination gains it. The form sets that; nobody picks a
            direction for an internal transfer.
  EXTERNAL  one end is ours, the other a counterparty. OUTGOING = source
            is ours, dest is the counterparty; INCOMING the reverse. The
            counterparty end's *_account_name is the counterparty name,
            its product NULL, its *_account_id whatever identifies it on
            the far side (a wallet address, a venue reference) -- typed,
            not resolved.

Amount is signed by direction, INCOMING + / OUTGOING -, and the validator
refuses a sign that disagrees. fee_amount is paid by the source on top.

There is no portfolio column, so nothing here consults scope: the routes
are admin-only in serverScope.mjs until scoping is rebuilt on
account -> portfolio.

Creds, connection and the refdata loaders are cashflow_db's: same
database, same refdata files, no second copy to drift.
"""
from __future__ import annotations
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

import cashflow_db

load_creds = cashflow_db.load_creds
connect = cashflow_db.connect


REQUIRED_FIELDS_INSERT = (
    "transfer_type", "direction",
    "source_account_name", "dest_account_name",
    "asset", "amount", "initiated_datetime", "user_id", "status",
)
REQUIRED_FIELDS_AMEND = REQUIRED_FIELDS_INSERT + ("deal_ref",)

VALID_TRANSFER_TYPES = {"INTERNAL", "EXTERNAL"}
VALID_DIRECTIONS = cashflow_db.VALID_DIRECTIONS
# A movement is either still moving or it has landed; there is no
# PROCESSED / SETTLED distinction for a transfer.
VALID_STATUSES = {"PENDING", "CONFIRMED", "COMPLETED", "CANCELLED"}
VALID_NETWORKS = cashflow_db.VALID_NETWORKS

# refdata accounts.json kind -> the account_type the gateway rule wants.
# crypto_settlement accounts have no gateway id.
_KIND_TO_TYPE = {
    "exchange": "EXCHANGE",
    "wallet": "WALLET",
    "broker": "BROKER",
    "bank": "BANK",
}


class ValidationError(ValueError):
    """Payload failed pre-DB validation. Raised before opening a txn."""


def _load_account_types() -> dict:
    """{account name: EXCHANGE|WALLET|BROKER|BANK} from refdata. {} on failure."""
    try:
        with open(cashflow_db.REFDATA_DIR / "accounts.json", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    out = {}
    for kind, typ in _KIND_TO_TYPE.items():
        for a in data.get(kind, []):
            if a.get("name"):
                out[a["name"]] = typ
    return out


def own_sides(p: dict) -> tuple[str, ...]:
    """Which ends of this transfer are OUR accounts: ('source', 'dest'),
    ('source',) or ('dest',). Read from transfer_type + direction, never
    from name lookups, so it holds even when refdata is unavailable."""
    if p.get("transfer_type") == "INTERNAL":
        return ("source", "dest")
    return ("source",) if p.get("direction") == "OUTGOING" else ("dest",)


def _amount(p: dict) -> Decimal:
    try:
        return Decimal(str(p["amount"]))
    except (InvalidOperation, TypeError, ValueError) as e:
        raise ValidationError(f"amount must be numeric, got {p['amount']!r}") from e


def _validate_one(p: dict, mode: str) -> None:
    required = REQUIRED_FIELDS_AMEND if mode == "amend" else REQUIRED_FIELDS_INSERT
    for f in required:
        v = p.get(f)
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValidationError(f"required field missing or empty: {f}")
    if p["transfer_type"] not in VALID_TRANSFER_TYPES:
        raise ValidationError(
            f"transfer_type must be one of {sorted(VALID_TRANSFER_TYPES)}, "
            f"got {p['transfer_type']!r}"
        )
    if p["direction"] not in VALID_DIRECTIONS:
        raise ValidationError(
            f"direction must be one of {sorted(VALID_DIRECTIONS)}, got {p['direction']!r}"
        )
    if p["status"] not in VALID_STATUSES:
        raise ValidationError(
            f"status must be one of {sorted(VALID_STATUSES)}, got {p['status']!r}"
        )
    amt = _amount(p)
    if amt == 0:
        raise ValidationError(f"amount must be non-zero, got {p['amount']!r}")
    # A transfer is only ever read as a balance movement, so a positive
    # OUTGOING would silently move money the wrong way. Refuse it here
    # rather than trust every client to sign correctly.
    if (p["direction"] == "OUTGOING") != (amt < 0):
        raise ValidationError(
            f"amount sign must follow direction: {p['direction']} expects "
            f"{'a negative' if p['direction'] == 'OUTGOING' else 'a positive'} "
            f"amount, got {p['amount']!r}"
        )
    if p.get("fee_amount") not in (None, "", 0):
        try:
            Decimal(str(p["fee_amount"]))
        except (InvalidOperation, TypeError, ValueError) as e:
            raise ValidationError(
                f"fee_amount must be numeric if set, got {p['fee_amount']!r}"
            ) from e
    if p["transfer_type"] == "INTERNAL" and p["direction"] != "OUTGOING":
        raise ValidationError(
            "INTERNAL transfer is booked OUTGOING from the source account "
            f"(amount negative), got {p['direction']}"
        )

    # Refdata-bound checks, failing open on an empty set exactly as
    # cashflow_db does (a refdata outage must not block the book).
    accts = cashflow_db._safe_load(cashflow_db._load_accounts_set)
    cps = cashflow_db._safe_load(cashflow_db._load_counterparties_set)
    ours = own_sides(p)
    for side in ("source", "dest"):
        name = p[f"{side}_account_name"]
        if side in ours:
            if accts and name not in accts:
                raise ValidationError(
                    f"{side}_account_name {name!r} not in refdata accounts "
                    f"({len(accts)} valid) — this end of a "
                    f"{p['transfer_type']} {p['direction']} transfer is ours"
                )
        elif cps and name not in cps:
            raise ValidationError(
                f"{side}_account_name {name!r} not in refdata counterparties "
                f"({len(cps)} valid) — this end of an EXTERNAL "
                f"{p['direction']} transfer is the counterparty"
            )
    if p["transfer_type"] == "INTERNAL" and p["source_account_name"] == p["dest_account_name"]:
        # Same account both ends is a real movement only between its
        # sub-accounts (spot -> funding, chain A -> chain B).
        ps = str(p.get("source_product") or "").strip().upper()
        pd = str(p.get("dest_product") or "").strip().upper()
        if not ps or not pd or ps == pd:
            raise ValidationError(
                f"INTERNAL transfer from {p['source_account_name']!r} to itself "
                f"needs two different products (e.g. SPOT -> FUNDING), got "
                f"{ps or '—'} and {pd or '—'}"
            )

    assets = cashflow_db._safe_load(cashflow_db._load_assets_set)
    if assets and p["asset"] not in assets:
        raise ValidationError(
            f"asset {p['asset']!r} not in refdata ({len(assets)} valid tokens)"
        )
    if p.get("network") and p["network"] not in VALID_NETWORKS:
        raise ValidationError(
            f"network {p['network']!r} not in NETWORKS list — must be one of "
            f"{len(VALID_NETWORKS)} uppercase chain names"
        )


def validate_payload(payload, *, mode: str) -> None:
    """Raise ValidationError if payload is bad. mode in {'insert', 'amend'}.

    Always a single dict: a transfer is one row with both ends on it.
    """
    if mode not in ("insert", "amend"):
        raise ValidationError(f"unknown mode: {mode}")
    if isinstance(payload, list):
        raise ValidationError("transfer payload must be a single dict, not a list")
    if not isinstance(payload, dict):
        raise ValidationError(f"payload must be dict, got {type(payload).__name__}")
    _validate_one(payload, mode)


def stamp_account_ids(payload: dict) -> None:
    """Resolve the gateway account_id for each end that is OURS, in place.

    The counterparty end is left exactly as typed (a wallet address, a
    venue reference). An own end already carrying an id is left alone too,
    so an amend does not overwrite a value someone corrected by hand; an
    unresolvable one stays NULL. Never raises.
    """
    types = _load_account_types()
    import account_id_resolve

    for side in own_sides(payload):
        key = f"{side}_account_id"
        if str(payload.get(key) or "").strip():
            continue
        name = payload.get(f"{side}_account_name")
        payload[key] = account_id_resolve.resolve(
            name, types.get(name), payload.get(f"{side}_product")
        )


# Column order matches apply_schema_transfer.py DDL, minus id (identity)
# and effective_* (set by SQL expressions NOW() / NULL in the INSERT).
DATA_COLUMNS = (
    "deal_ref",
    "transfer_type",
    "direction",
    "source_account_name",
    "source_product",
    "source_account_id",
    "dest_account_name",
    "dest_product",
    "dest_account_id",
    "asset",
    "amount",
    "fee_asset",
    "fee_amount",
    "initiated_datetime",
    "completed_datetime",
    "network",
    "ext_transfer_id",
    "user_id",
    "status",
    "comment",
    # Who made THIS version. user_id stays the original author.
    "updated_by",
)


def payload_to_columns(payload: dict, *, deal_ref: str | None = None) -> tuple[tuple[str, ...], tuple]:
    """Convert form JSON to (column_names, values) for INSERT.

    `deal_ref` is None on insert -- the column is omitted so the DB default
    ('MTR' || lpad(nextval('trade_seq_transfer'),8,'0')) assigns it -- and
    the existing ref on amend. Never trusted from the client on insert.
    Products are their own columns, so account names are stored bare (no
    "<name>_<PRODUCT>" baking as on the other books).
    """
    cols = tuple(c for c in DATA_COLUMNS if not (c == "deal_ref" and deal_ref is None))
    vals = []
    for col in cols:
        if col == "deal_ref":
            vals.append(deal_ref)
        elif col == "fee_amount":
            v = payload.get("fee_amount")
            vals.append("0" if v in (None, "") else v)
        elif col in ("source_product", "dest_product"):
            v = cashflow_db._coerce_str_or_none(payload.get(col))
            vals.append(str(v).strip().upper() if v else None)
        else:
            vals.append(cashflow_db._coerce_str_or_none(payload.get(col)))
    return cols, tuple(vals)


def _json_safe(v):
    if isinstance(v, Decimal):
        return format(v.normalize(), "f") if v == v.to_integral_value() else str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def row_to_payload(columns, row) -> dict:
    """psycopg2 row tuple -> JSON-safe dict keyed by column name.

    Adds read-only conveniences for Deal Enquiry, which merges the books
    into one table keyed on the cashflow column names: txn_type (the table
    has no such column), trade_date / value_date (the initiated / completed
    times), account (our end, with its product) and counterparty (the far
    end). The real columns are all still present and the form loads from
    those, never from the aliases.
    """
    out = {col: _json_safe(val) for col, val in zip(columns, row)}
    out["txn_type"] = "TRANSFER"
    out["trade_date"] = out.get("initiated_datetime")
    out["value_date"] = out.get("completed_datetime")
    ours = own_sides(out)
    own = "source" if "source" in ours else "dest"
    far = "dest" if own == "source" else "source"
    prod = out.get(f"{own}_product")
    out["account"] = (
        f"{out.get(f'{own}_account_name')}{' · ' + prod if prod else ''}"
        if out.get(f"{own}_account_name") else None
    )
    out["counterparty"] = out.get(f"{far}_account_name")
    return out
