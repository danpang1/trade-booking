"""One-shot migration: rename direction values PAY/RECEIVE → OUTGOING/INCOMING.

Run once against UAT after deploying the matching code changes.

Steps (all wrapped in one transaction):
  1. Drop the existing CHECK constraint on direction.
  2. UPDATE rows: PAY → OUTGOING, RECEIVE → INCOMING.
  3. Add a new CHECK constraint with the new values.

Idempotent: re-running after a successful migration is a no-op (the UPDATE
matches nothing and the constraint swap is gated on what's actually there).
"""
from cashflow_db import connect


# Find any CHECK constraint on trades_cashflow that mentions the direction
# column. apply_schema_cashflow.py declared it inline (no explicit name), so
# Postgres auto-named it trades_cashflow_direction_check.
FIND_CHECK_SQL = """
    SELECT conname, pg_get_constraintdef(oid)
    FROM pg_constraint
    WHERE conrelid = 'trades_cashflow'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) ILIKE '%direction%';
"""


def main():
    conn = connect()
    cur = conn.cursor()

    cur.execute("SELECT direction, COUNT(*) FROM trades_cashflow GROUP BY direction ORDER BY direction;")
    print(f"before: {cur.fetchall()}")

    cur.execute(FIND_CHECK_SQL)
    constraints = cur.fetchall()
    print(f"existing direction check constraints: {constraints}")

    try:
        for name, _def in constraints:
            print(f"  dropping constraint {name}")
            cur.execute(f'ALTER TABLE trades_cashflow DROP CONSTRAINT "{name}";')

        cur.execute("UPDATE trades_cashflow SET direction='OUTGOING' WHERE direction='PAY';")
        pay_count = cur.rowcount
        cur.execute("UPDATE trades_cashflow SET direction='INCOMING' WHERE direction='RECEIVE';")
        rec_count = cur.rowcount
        print(f"  updated: PAY→OUTGOING={pay_count}, RECEIVE→INCOMING={rec_count}")

        cur.execute(
            "ALTER TABLE trades_cashflow "
            "ADD CONSTRAINT trades_cashflow_direction_check "
            "CHECK (direction IN ('INCOMING','OUTGOING'));"
        )
        print("  added new CHECK constraint")
    except Exception:
        conn.rollback()
        raise
    conn.commit()

    cur.execute("SELECT direction, COUNT(*) FROM trades_cashflow GROUP BY direction ORDER BY direction;")
    print(f"after:  {cur.fetchall()}")

    conn.close()


if __name__ == "__main__":
    main()
