"""Helpers for the loan_cashflow_map link table.

This module never opens its own DB connection — it operates on a
cursor passed in by the caller (typically cashflow_insert.py /
cashflow_amend.py), so the mapping change rides on the same
transaction as the cashflow change.
"""
from __future__ import annotations
import re

MLA_RE = re.compile(r"^MLA\d{8}$")
MCF_RE = re.compile(r"^MCF\d{8}$")


class MappingError(ValueError):
    """Invalid mapping payload — surfaces back to the API as a 400."""


# cashflow_type + direction → mapping_type, when the operator doesn't
# pass mapping_type explicitly. Anything not in this dict → NULL,
# which the CHECK constraint still allows (manual mappings can be
# untyped).
def derive_mapping_type(cashflow_type: str | None, direction: str | None) -> str | None:
    ct = (cashflow_type or "").upper()
    if ct == "LOAN":
        return "PRINCIPAL_DISBURSE"
    if ct == "LOAN REPAYMENT":
        return "PRINCIPAL_REPAY"
    if ct in ("INTEREST EXPENSE", "INTEREST INCOME"):
        return "INTEREST"
    # Collateral cashflow types aren't in the CASHFLOW_TYPES list yet;
    # add them here when the form does. FEE / RETAINER / etc. map to
    # nothing — the operator can still link manually.
    return None


def _norm_refs(refs) -> list[str]:
    """Trim, dedupe (preserve order), reject anything not MLA00000000-shaped."""
    if refs is None:
        return []
    if not isinstance(refs, list):
        raise MappingError(f"loan_deal_refs must be a list, got {type(refs).__name__}")
    seen: set[str] = set()
    out: list[str] = []
    for r in refs:
        if not isinstance(r, str):
            raise MappingError(f"loan_deal_ref must be a string, got {r!r}")
        s = r.strip()
        if not s:
            continue
        if not MLA_RE.match(s):
            raise MappingError(f"loan_deal_ref {s!r} doesn't match MLA00000000 pattern")
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def set_mappings_for_cashflow(
    cur,
    *,
    cashflow_deal_ref: str,
    loan_deal_refs,
    user_id: str,
    cashflow_type: str | None = None,
    direction: str | None = None,
) -> list[dict]:
    """Replace the set of loan mappings for one cashflow.

    Idempotent: deletes existing rows for this cashflow_deal_ref, then
    inserts one row per ref in `loan_deal_refs`. Must be called inside
    an open transaction (the caller commits).

    Validates each ref exists as a *live* row in trades_loan
    (effective_end IS NULL). Mapping to a closed/cancelled loan row
    is rejected. If the operator needs to map to a cancelled loan
    they can amend the cashflow after un-cancelling, or skip the
    auto-validation and SQL it manually.

    Returns the list of mapping rows it inserted (for echo back to
    the API caller).
    """
    if not isinstance(cashflow_deal_ref, str) or not MCF_RE.match(cashflow_deal_ref):
        raise MappingError(
            f"cashflow_deal_ref must match MCF00000000, got {cashflow_deal_ref!r}"
        )
    refs = _norm_refs(loan_deal_refs)

    # Validate referenced loans exist + are live. Single round-trip.
    if refs:
        cur.execute(
            "SELECT deal_ref FROM trades_loan "
            "WHERE deal_ref = ANY(%s) AND effective_end IS NULL",
            (refs,),
        )
        found = {r[0] for r in cur.fetchall()}
        missing = [r for r in refs if r not in found]
        if missing:
            raise MappingError(
                f"loan deal_refs not found or not live: {missing}"
            )

    # Replace-in-place: blow away existing mappings for this cashflow,
    # then re-insert. Single-cashflow blast radius; safe inside a txn.
    cur.execute(
        "DELETE FROM loan_cashflow_map WHERE cashflow_deal_ref = %s",
        (cashflow_deal_ref,),
    )

    if not refs:
        return []

    mapping_type = derive_mapping_type(cashflow_type, direction)
    rows = [(loan_ref, cashflow_deal_ref, mapping_type, None, user_id) for loan_ref in refs]
    cur.executemany(
        "INSERT INTO loan_cashflow_map "
        "(loan_deal_ref, cashflow_deal_ref, mapping_type, mapped_amount, mapped_by) "
        "VALUES (%s, %s, %s, %s, %s)",
        rows,
    )
    return [
        {
            "loan_deal_ref": r[0],
            "cashflow_deal_ref": r[1],
            "mapping_type": r[2],
            "mapped_amount": r[3],
            "mapped_by": r[4],
        }
        for r in rows
    ]


# ─── Read-side SQL helpers ────────────────────────────────────────
# Used by the LEFT-JOIN queries in cashflow_get / _recent / _history
# and the loan_* equivalents. Centralised so the JSON shape is
# consistent across all 6 endpoints.

# Cashflow-side aggregate: for each cashflow row, build a JSON array
# of its loan mappings. Caller composes this into a larger SELECT
# with `LEFT JOIN loan_cashflow_map m ON m.cashflow_deal_ref = t.deal_ref`
# and `GROUP BY` on the trades_cashflow PK columns.
CASHFLOW_MAPPINGS_JSON_AGG = (
    "COALESCE(json_agg(json_build_object("
    "  'counterpart_deal_ref', m.loan_deal_ref,"
    "  'mapping_type', m.mapping_type,"
    "  'mapped_amount', m.mapped_amount"
    ") ORDER BY m.loan_deal_ref) FILTER (WHERE m.loan_deal_ref IS NOT NULL), '[]'::json)"
    " AS mappings"
)

# Loan-side aggregate: include the linked cashflow's headline economics
# (direction / amount / asset) so the UI can compute "X paid / Y received"
# without a second query.
LOAN_MAPPINGS_JSON_AGG = (
    "COALESCE(json_agg(json_build_object("
    "  'counterpart_deal_ref', m.cashflow_deal_ref,"
    "  'mapping_type', m.mapping_type,"
    "  'mapped_amount', m.mapped_amount,"
    "  'cashflow_type', cf.cashflow_type,"
    "  'direction', cf.direction,"
    "  'amount', cf.amount,"
    "  'asset', cf.asset,"
    "  'trade_date', cf.trade_date,"  # used by the loan-schedule modal for chronological ordering
    "  'value_date', cf.value_date,"   # shown in the Linked Cashflows table
    "  'txid_reference', cf.txid_reference"  # shown in the Linked Cashflows table
    # Filter the aggregate on (a) a real mapping row AND (b) the
    # joined cashflow actually surviving the JOIN predicate (live +
    # not cancelled). Without the cf.deal_ref guard a cancelled
    # cashflow would still appear with null cashflow_type / amount.
    ") ORDER BY cf.trade_date, m.cashflow_deal_ref) FILTER (WHERE m.cashflow_deal_ref IS NOT NULL AND cf.deal_ref IS NOT NULL), '[]'::json)"
    " AS mappings"
)
