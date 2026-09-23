"""Apply the manual_trade / manual_cashflow schema to the tech-team Postgres.

Reads the DDL from migrations/0001_manual_trade_cashflow.sql (source of truth)
and executes it against the TECH DB (creds via scripts/tech_db.py — TECH_DB_*
env vars or the `# TECH DB` .env block). Idempotent: the DDL is all
CREATE ... IF NOT EXISTS / DO-guarded, so re-running is safe.

Usage:  python scripts/apply_schema_manual_tables.py
"""
from __future__ import annotations
from pathlib import Path

import tech_db

REPO = Path(__file__).resolve().parents[1]
DDL_FILE = REPO / "migrations" / "0001_manual_trade_cashflow.sql"

_TABLES = ("manual_trade", "manual_cashflow")
_ENUMS = ("manual_status", "manual_trade_side", "manual_cashflow_kind")
_SEQUENCES = ("manual_trade_deal_ref_seq", "manual_cashflow_deal_ref_seq")


def main() -> None:
    ddl = DDL_FILE.read_text(encoding="utf-8")

    conn = tech_db.connect()
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(ddl)
    print(f"applied {DDL_FILE.relative_to(REPO)} OK\n")

    # ── Verify enums ──────────────────────────────────────────────────
    cur.execute(
        "SELECT typname FROM pg_type WHERE typname = ANY(%s) ORDER BY typname",
        (list(_ENUMS),),
    )
    got = [r[0] for r in cur.fetchall()]
    print(f"enums: {got}")
    missing = set(_ENUMS) - set(got)
    if missing:
        raise SystemExit(f"MISSING enums: {sorted(missing)}")

    # ── Verify sequences ──────────────────────────────────────────────
    cur.execute(
        "SELECT sequencename FROM pg_sequences WHERE sequencename = ANY(%s) ORDER BY 1",
        (list(_SEQUENCES),),
    )
    got = [r[0] for r in cur.fetchall()]
    print(f"sequences: {got}")
    missing = set(_SEQUENCES) - set(got)
    if missing:
        raise SystemExit(f"MISSING sequences: {sorted(missing)}")

    # ── Verify tables (columns / indexes / constraints) ───────────────
    for table in _TABLES:
        cur.execute(
            """
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = %s
            ORDER BY ordinal_position
            """,
            (table,),
        )
        cols = cur.fetchall()
        if not cols:
            raise SystemExit(f"MISSING table: {table}")
        print(f"\n{table} columns: {len(cols)}")
        for col in cols:
            null = "NULL" if col[2] == "YES" else "NOT NULL"
            print(f"  {col[0]:20s} {col[1]:24s} {null:9s} {col[3] or ''}")

        cur.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = %s ORDER BY indexname",
            (table,),
        )
        print(f"  indexes: {[r[0] for r in cur.fetchall()]}")

        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = %s::regclass ORDER BY contype",
            (table,),
        )
        print("  constraints:")
        for row in cur.fetchall():
            print(f"    {row[0]}")

    conn.close()
    print("\nOK — manual_trade / manual_cashflow present.")


if __name__ == "__main__":
    main()
