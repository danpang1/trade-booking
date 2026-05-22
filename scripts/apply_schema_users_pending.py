"""Extend `users` table with pending-registration columns. Idempotent.

Adds:
  - status         VARCHAR(16) NOT NULL DEFAULT 'active' CHECK ('pending'|'active')
  - approved_at    TIMESTAMPTZ NULL
  - approved_by    VARCHAR(64) NULL
  - relaxes role NOT NULL (pending rows have NULL role until approved)
  - CHECK: status='pending' OR role IS NOT NULL
"""
from __future__ import annotations
import cashflow_db


DDL = """
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS status      VARCHAR(16) NOT NULL DEFAULT 'active',
  ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS approved_by VARCHAR(64);

-- Postgres has no `ADD CONSTRAINT IF NOT EXISTS`; DROP-then-ADD inside one
-- transaction is the idiomatic idempotent pattern. Runs inside `with conn:`
-- so the constraint is never observable-missing to concurrent readers.
ALTER TABLE users
  DROP CONSTRAINT IF EXISTS users_status_check;
ALTER TABLE users
  ADD  CONSTRAINT users_status_check CHECK (status IN ('pending','active'));

-- DROP NOT NULL is itself idempotent (no-op if already nullable).
ALTER TABLE users ALTER COLUMN role DROP NOT NULL;

ALTER TABLE users
  DROP CONSTRAINT IF EXISTS users_active_has_role;
ALTER TABLE users
  ADD  CONSTRAINT users_active_has_role CHECK (status = 'pending' OR role IS NOT NULL);
"""


def main() -> None:
    conn = cashflow_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(DDL)
        print("ok: users table extended for registration flow")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
