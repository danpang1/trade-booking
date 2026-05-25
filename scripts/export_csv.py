"""Pure-logic helpers for the blotter CSV export.

Transforms a live cashflow / spot row payload (as produced by
cashflow_db.row_to_payload / spot_db.row_to_payload) into the 18-column
blotter shape requested by the MO team. Strict separation from DB / IO
so each transform has direct unit-test coverage.

Used by scripts/export_blotter.py (the DB-touching wrapper).
"""
from __future__ import annotations
import csv
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable, Sequence


BLOTTER_COLUMNS: tuple[str, ...] = (
    "Input Date",
    "Month Year",
    "Deal Reference",
    "Portfolio",
    "Portfolio Name",
    "Counterparty",
    "Txn Type",
    "Trade Type",
    "Asset",
    "Amount",
    "Fee Asset",
    "Fee Amount",
    "Trade Date",
    "Value Date",
    "Account",
    "Account Type",
    "TXID/REFERENCE",
    "Comment",
)


_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def fmt_month_year(iso: str | None) -> str:
    """Return e.g. 'May 2026' from an ISO timestamp; '' on None / bad input."""
    if not iso:
        return ""
    try:
        # Postgres TIMESTAMPTZ renders as '2026-05-19 08:42:00+00' or
        # ISO 8601 — strptime needs separators normalized. Use fromisoformat
        # which accepts both 'T' and ' ' separators in Py 3.11+.
        normalized = str(iso).replace(" ", "T")
        d = datetime.fromisoformat(normalized)
    except (ValueError, TypeError):
        return ""
    return f"{_MONTH_NAMES[d.month - 1]} {d.year}"


def _sign_amount(amount, direction: str, *, positive: str, negative: str) -> str:
    """Return amount as a string with sign applied per direction.

    `positive` and `negative` are the direction labels that mean
    add and subtract respectively (e.g. INCOMING/OUTGOING for cashflow,
    LONG/SHORT for spot base leg). If the raw value is already negative
    we leave it alone — never double-flip.
    """
    if amount in (None, ""):
        return ""
    try:
        d = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        return str(amount)
    if not d.is_finite():
        return str(amount)
    if d == 0:
        return "0"
    abs_d = abs(d)
    if direction == positive:
        return _decimal_str(abs_d)
    if direction == negative:
        return _decimal_str(-abs_d)
    return _decimal_str(d)


def _decimal_str(d: Decimal) -> str:
    """Render a Decimal without exponent notation and without trailing zeros."""
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s if s else "0"


def _str_or_empty(v) -> str:
    if v is None:
        return ""
    return str(v)


def _resolve_inter_ptf_counterparty(raw, portfolios: Sequence[dict]) -> str:
    """Look up portfolio name when counterparty is a portfolio number.

    Returns the name on hit, the raw value on miss. portfolios entries
    are expected to be {'number': int, 'name': str}.
    """
    if raw is None:
        return ""
    try:
        target = int(str(raw).strip())
    except (ValueError, AttributeError):
        return str(raw)
    for p in portfolios:
        try:
            p_num = int(p.get("number", -1))
        except (ValueError, TypeError):
            continue
        if p_num == target:
            return str(p.get("name", raw))
    return str(raw)


def cashflow_to_row(payload: dict, *, portfolios: Sequence[dict]) -> dict:
    """Map one live cashflow payload to a single blotter row."""
    cf_type = payload.get("cashflow_type") or ""
    counterparty_raw = payload.get("counterparty")
    if cf_type == "INTER PTF FUNDING":
        counterparty = _resolve_inter_ptf_counterparty(counterparty_raw, portfolios)
    else:
        counterparty = _str_or_empty(counterparty_raw)

    return {
        "Input Date": _str_or_empty(payload.get("first_effective_start")),
        "Month Year": fmt_month_year(payload.get("trade_date")),
        "Deal Reference": _str_or_empty(payload.get("deal_ref")),
        "Portfolio": _str_or_empty(payload.get("portfolio_id")),
        "Portfolio Name": _str_or_empty(payload.get("portfolio_name")),
        "Counterparty": counterparty,
        "Txn Type": _str_or_empty(payload.get("txn_type")),
        "Trade Type": cf_type,
        "Asset": _str_or_empty(payload.get("asset")),
        "Amount": _sign_amount(
            payload.get("amount"),
            payload.get("direction") or "",
            positive="INCOMING",
            negative="OUTGOING",
        ),
        "Fee Asset": _str_or_empty(payload.get("fee_asset")),
        "Fee Amount": _str_or_empty(payload.get("fee_amount")),
        "Trade Date": _str_or_empty(payload.get("trade_date")),
        "Value Date": _str_or_empty(payload.get("value_date")),
        "Account": _str_or_empty(payload.get("account")),
        "Account Type": _str_or_empty(payload.get("account_type")),
        "TXID/REFERENCE": _str_or_empty(payload.get("txid_reference")),
        "Comment": _str_or_empty(payload.get("comment")),
    }


def _spot_common(payload: dict) -> dict:
    """Columns that are identical across every spot leg of one trade."""
    return {
        "Input Date": _str_or_empty(payload.get("first_effective_start")),
        "Month Year": fmt_month_year(payload.get("trade_date")),
        "Deal Reference": _str_or_empty(payload.get("deal_ref")),
        "Portfolio": _str_or_empty(payload.get("portfolio_id")),
        "Portfolio Name": _str_or_empty(payload.get("portfolio_name")),
        "Counterparty": _str_or_empty(payload.get("counterparty")),
        "Txn Type": "SPOT",
        "Trade Type": _str_or_empty(payload.get("direction")),
        "Trade Date": _str_or_empty(payload.get("trade_date")),
        "Value Date": _str_or_empty(payload.get("value_date")),
        "Account": _str_or_empty(payload.get("account")),
        "Account Type": _str_or_empty(payload.get("account_type")),
        "TXID/REFERENCE": _str_or_empty(payload.get("txid_reference")),
        "Comment": _str_or_empty(payload.get("comment")),
    }


def spot_to_rows(payload: dict) -> list[dict]:
    """Explode a spot trade into 2 (no fee) or 3 (with fee) blotter rows."""
    direction = payload.get("direction") or ""
    common = _spot_common(payload)

    base = {
        **common,
        "Asset": _str_or_empty(payload.get("base_asset")),
        "Amount": _sign_amount(
            payload.get("base_amount"),
            direction,
            positive="LONG",
            negative="SHORT",
        ),
        "Fee Asset": "",
        "Fee Amount": "",
    }
    quote = {
        **common,
        "Asset": _str_or_empty(payload.get("quote_asset")),
        "Amount": _sign_amount(
            payload.get("quote_amount"),
            direction,
            positive="SHORT",
            negative="LONG",
        ),
        "Fee Asset": "",
        "Fee Amount": "",
    }
    rows = [base, quote]

    fee_amount = payload.get("fee_amount")
    if fee_amount not in (None, "", 0, "0"):
        try:
            if Decimal(str(fee_amount)) != 0:
                fee = {
                    **common,
                    "Asset": _str_or_empty(payload.get("fee_asset")),
                    "Amount": _sign_amount(
                        payload.get("fee_amount"),
                        "OUTGOING",
                        positive="INCOMING",
                        negative="OUTGOING",
                    ),
                    "Fee Asset": _str_or_empty(payload.get("fee_asset")),
                    "Fee Amount": _str_or_empty(payload.get("fee_amount")),
                }
                rows.append(fee)
        except (InvalidOperation, TypeError, ValueError):
            pass

    return rows


def serialize_csv(rows: Iterable[dict]) -> str:
    """Serialize rows (dicts keyed by BLOTTER_COLUMNS) to a CSV string."""
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=list(BLOTTER_COLUMNS),
        quoting=csv.QUOTE_MINIMAL,
        extrasaction="ignore",
        restval="",
    )
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return buf.getvalue()
