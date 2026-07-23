"""Add per-app access flag to `users`. Idempotent.

Adds:
  - access_tms  BOOLEAN NOT NULL DEFAULT TRUE

TMS (trade-booking) auth refuses login / session resolution when
access_tms is false. ACE Terminal ignores the column, so an
access_tms=false user keeps ACE access with the same credentials.
"""
from __future__ import annotations
import cashflow_db


DDL = """
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS access_tms BOOLEAN NOT NULL DEFAULT TRUE;
"""


def main() -> None:
    conn = cashflow_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(DDL)
        print("ok: users.access_tms added (default TRUE)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
