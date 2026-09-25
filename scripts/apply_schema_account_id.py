"""Add the gateway `account_id` column to the trades tables. Idempotent.

Adds:
  - trades_cashflow.account_id  TEXT NULL
  - trades_spot.account_id      TEXT NULL
  - trades_loan.account_id      TEXT NULL

TEXT, not an integer, to match manual_trade.account_id / fee_event.account_id
and the position service's string balance key -- the id is an identifier, not a
number anything does arithmetic on, and its leading digits matter.

Nullable and appended: rows booked before this stay NULL rather than being
rewritten. These are SCD Type 2 tables, so a backfill would mean new row
versions for every historic trade.

trades_loan gets the column for uniformity but nothing populates it yet: the
table has no account / account_type to resolve an id from.
"""
from __future__ import annotations
import cashflow_db


TABLES = ("trades_cashflow", "trades_spot", "trades_loan")

DDL = "\n".join(
    f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS account_id TEXT;" for t in TABLES
)


def main() -> None:
    conn = cashflow_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(DDL)
        print("ok: account_id added to " + ", ".join(TABLES))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
