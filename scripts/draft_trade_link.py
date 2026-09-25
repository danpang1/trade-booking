"""Keep a draft and the live trade row it created in step.

A Colossus booking used to land ONLY in bookings_draft, and the trade row was
created on approval. It now lands in both at once: the trade goes into
trades_cashflow / trades_spot as PENDING the moment it is booked, so it is
visible in Deal Enquiry, the exports and the position feed before anyone has
approved it. Approval and rejection then MOVE that row rather than creating
one.

Every caller runs inside the draft's own transaction -- drafts and trades
share one Postgres connection (draft_db.connect IS cashflow_db.connect) -- so
a failure anywhere rolls back both the draft and the trade. There is no window
in which one exists without the other.

trades_* are SCD Type 2, so a status change is not an UPDATE: it closes the
live version and inserts a new one. The new version is built with
INSERT ... SELECT over the table's own DATA_COLUMNS, which carries every
column forward untouched (including account_id) and cannot silently drop a
column added later.
"""
from __future__ import annotations

import authorship
import cashflow_db
import spot_db


# category -> (table, db module). LOAN has no draft path.
_TABLES = {
    "CASHFLOW": ("trades_cashflow", cashflow_db),
    "SPOT": ("trades_spot", spot_db),
}


class LinkError(Exception):
    """The draft's trade row is missing or not amendable."""


def category_table(category):
    """`(table_name, db_module)` for a draft category, or None if it has none."""
    return _TABLES.get(str(category or "").upper())


def amend_status(cur, category, deal_ref, new_status, *, user_id=None,
                 updated_by=None):
    """Move the live trade row for `deal_ref` to `new_status`. Returns the row.

    SCD2: closes the current version and inserts a copy carrying every column
    forward, with `status` (and optionally `user_id`) replaced.

    `user_id` exists for approval, which strips the "claude:" prefix so the
    live trade attributes to the bare username -- the Claude Code provenance
    stays on bookings_draft.source.
    """
    hit = category_table(category)
    if hit is None:
        raise LinkError(f"no trade table for category {category!r}")
    table, db = hit

    cur.execute(
        f"UPDATE {table} SET effective_end = NOW() "
        " WHERE deal_ref = %s AND effective_end IS NULL "
        " RETURNING id",
        (deal_ref,),
    )
    closed = cur.fetchone()
    if closed is None:
        raise LinkError(
            f"{deal_ref} has no live row to move to {new_status} "
            f"(already amended, cancelled, or never created)"
        )

    # Carry every data column forward, overriding only what changes. Built
    # from DATA_COLUMNS so a column added to the table later is copied too.
    # Created By stays whoever booked it; the approver/rejecter is recorded
    # separately rather than taking ownership of someone else's trade.
    overrides = {"status": new_status}
    if user_id is not None:
        overrides["user_id"] = user_id
    if updated_by is not None:
        overrides["updated_by"] = updated_by

    # Args MUST follow DATA_COLUMNS order, not the order the overrides were
    # added: the placeholders are emitted column by column. Building the list
    # by append order put the status into user_id and vice versa.
    select_list = ", ".join(
        "%s" if c in overrides else f'"{c}"' for c in db.DATA_COLUMNS
    )
    args = [overrides[c] for c in db.DATA_COLUMNS if c in overrides]
    col_list = ", ".join(f'"{c}"' for c in db.DATA_COLUMNS)
    cur.execute(
        f"INSERT INTO {table} ({col_list}, effective_start, effective_end) "
        f"SELECT {select_list}, NOW(), NULL FROM {table} WHERE id = %s "
        " RETURNING *",
        (*args, closed[0]),
    )
    cols = [d.name for d in cur.description]
    return db.row_to_payload(cols, cur.fetchone())


def replace_from_payload(cur, category, deal_ref, payload):
    """Restate the live trade row from `payload`. Returns the new row.

    Editing a draft has to move the trade with it: the row was booked when the
    draft was created, so leaving it alone would let the book disagree with
    the draft it came from. Same SCD2 shape as amend_status, but every column
    is rebuilt from the edited payload rather than carried forward.
    """
    hit = category_table(category)
    if hit is None:
        raise LinkError(f"no trade table for category {category!r}")
    table, db = hit

    cur.execute(
        f"UPDATE {table} SET effective_end = NOW() "
        " WHERE deal_ref = %s AND effective_end IS NULL "
        " RETURNING id",
        (deal_ref,),
    )
    if cur.fetchone() is None:
        raise LinkError(f"{deal_ref} has no live row to restate")

    authorship.apply_on_amend(cur, table, payload, deal_ref)
    cols, vals = db.payload_to_columns(payload, deal_ref=deal_ref)
    col_list = ", ".join(cols + ("effective_start", "effective_end"))
    placeholders = ", ".join(["%s"] * len(cols)) + ", NOW(), NULL"
    cur.execute(
        f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) RETURNING *",
        vals,
    )
    out_cols = [d.name for d in cur.description]
    return db.row_to_payload(out_cols, cur.fetchone())


def mirror_amend(category, row):
    """Push a status change into the tech DB's manual_trade / manual_cashflow.

    Best-effort and silent on failure, exactly like the insert path: the
    mirror must never fail a booking. Without this the mirror keeps the old
    status and the two databases quietly disagree.
    """
    try:
        import manual_write

        if str(category).upper() == "SPOT":
            manual_write.write_manual_trade_amend(row)
        else:
            manual_write.write_manual_cashflow_amend(row)
    except Exception:  # noqa: BLE001
        pass
