"""Add `account_id` and `updated_by` to the trades tables. Idempotent.

Adds, on trades_cashflow / trades_spot / trades_loan:
  - account_id  TEXT NULL   the gateway sub-account id
  - updated_by  TEXT NULL   who made THIS version

TEXT, not an integer, to match manual_trade.account_id / fee_event.account_id
and the position service's string balance key -- the id is an identifier, not a
number anything does arithmetic on, and its leading digits matter.

Nullable and appended: rows booked before this stay NULL rather than being
rewritten. These are SCD Type 2 tables, so a backfill would mean new row
versions for every historic trade.

trades_loan gets account_id for uniformity but nothing populates it yet: the
table has no account / account_type to resolve an id from. updated_by applies
to all three.

`user_id` is CREATED BY and never changes; `updated_by` is whoever made this
version. Before this, an amend stamped user_id from the session, so correcting
someone else's trade silently took ownership of it.
"""
from __future__ import annotations
import cashflow_db


TABLES = ("trades_cashflow", "trades_spot", "trades_loan")
COLUMNS = ("account_id", "updated_by")

DDL = "\n".join(
    f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS {c} TEXT;"
    for t in TABLES for c in COLUMNS
)


def main() -> None:
    conn = cashflow_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(DDL)
        print("ok: %s added to %s" % (", ".join(COLUMNS), ", ".join(TABLES)))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
