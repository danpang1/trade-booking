"""Migration: surrogate `id` PK + table-level deal_ref default.

For each trades_* table this:
  1. creates an explicit per-table id sequence  (trades_<t>_id_seq),
  2. adds  id BIGINT NOT NULL DEFAULT nextval(seq)  (back-fills existing rows),
     and marks the sequence OWNED BY the column,
  3. swaps the PRIMARY KEY from (deal_ref, effective_start) to (id),
     keeping (deal_ref, effective_start) as a UNIQUE constraint so the
     bitemporal version integrity is preserved,
  4. sets deal_ref's DEFAULT to the prefixed sequence expression
     ('MCF' || lpad(nextval('trade_seq_cashflow')::text, 8, '0')), so new
     bookings get their deal-ref from the database (the app stops supplying
     it on insert; amends still pass the existing ref).

Idempotent: every step is guarded by introspection, so re-running is a
no-op once applied. Dry-run by default — pass --apply to write. Each table
is migrated in its own transaction.

Credentials: `#MO DB UAT` block in /.env, or MO_DB_* env vars (point those
at prod to run there).

Usage:
    python scripts/migrate_id_pk_and_dealref_default.py            # dry-run
    python scripts/migrate_id_pk_and_dealref_default.py --apply    # write
    # optional: floor the id sequence (e.g. stagger prod into a higher range)
    python scripts/migrate_id_pk_and_dealref_default.py --apply --id-start 1000000
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path

import psycopg2

REPO = Path(__file__).resolve().parents[1]
ENV = REPO / ".env"

# table -> (deal-ref prefix, deal-ref sequence used by the column default)
TABLES = {
    "trades_cashflow": ("MCF", "trade_seq_cashflow"),
    "trades_loan": ("MLA", "trade_seq_loan"),
    "trades_spot": ("MFX", "trade_seq_spot"),
}


def _load_creds() -> dict[str, str]:
    env_creds = {
        k: os.environ[f"MO_DB_{k.upper()}"]
        for k in ("host", "port", "database", "username", "password")
        if f"MO_DB_{k.upper()}" in os.environ
    }
    if all(k in env_creds for k in ("host", "database", "username", "password")):
        env_creds.setdefault("port", "5432")
        return env_creds
    creds: dict[str, str] = {}
    in_block = False
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if "MO DB UAT" in s.upper():
            in_block = True
            continue
        if not in_block:
            continue
        if not s or s.startswith("#"):
            if s.startswith("#") and "MO DB UAT" not in s.upper():
                break
            continue
        if ":" in s:
            k, _, v = s.partition(":")
            key = k.strip().lower()
            if key.startswith("mo_db_"):
                key = key[len("mo_db_"):]
            creds[key] = v.strip()
    return creds


def _has_column(cur, table, col):
    cur.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name=%s AND column_name=%s", (table, col))
    return cur.fetchone() is not None


def _pk_columns(cur, table):
    cur.execute("""
        SELECT a.attname
        FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=ANY(c.conkey)
        WHERE c.conrelid=%s::regclass AND c.contype='p'
        ORDER BY array_position(c.conkey, a.attnum)
    """, (table,))
    return [r[0] for r in cur.fetchall()]


def _has_unique(cur, table, cols):
    cur.execute("""
        SELECT c.conname,
               array_agg(a.attname ORDER BY array_position(c.conkey, a.attnum))
        FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=ANY(c.conkey)
        WHERE c.conrelid=%s::regclass AND c.contype='u'
        GROUP BY c.conname
    """, (table,))
    want = list(cols)
    return any(list(got) == want for _, got in cur.fetchall())


def _dealref_default(cur, table):
    cur.execute("""
        SELECT pg_get_expr(d.adbin, d.adrelid)
        FROM pg_attribute a
        JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
        WHERE a.attrelid=%s::regclass AND a.attname='deal_ref'
    """, (table,))
    row = cur.fetchone()
    return row[0] if row else None


def migrate_table(cur, table, prefix, seq, id_start, apply):
    id_seq = f"{table}_id_seq"
    steps = []

    if not _has_column(cur, table, "id"):
        steps.append((
            f"create sequence {id_seq} + add id column (back-fills rows)",
            [
                f"CREATE SEQUENCE IF NOT EXISTS {id_seq} "
                f"INCREMENT BY 1 MINVALUE 1 START 1 CACHE 1 NO CYCLE",
                f"ALTER TABLE {table} ADD COLUMN id BIGINT NOT NULL "
                f"DEFAULT nextval('{id_seq}')",
                f"ALTER SEQUENCE {id_seq} OWNED BY {table}.id",
            ],
        ))

    if _pk_columns(cur, table) != ["id"]:
        steps.append((
            "swap PRIMARY KEY -> (id), keep (deal_ref, effective_start) UNIQUE",
            [
                f"ALTER TABLE {table} DROP CONSTRAINT {table}_pkey",
                f"ALTER TABLE {table} ADD CONSTRAINT {table}_pkey PRIMARY KEY (id)",
            ],
        ))

    if not _has_unique(cur, table, ["deal_ref", "effective_start"]):
        steps.append((
            "add UNIQUE (deal_ref, effective_start)",
            [f"ALTER TABLE {table} ADD CONSTRAINT uq_{table}_version "
             f"UNIQUE (deal_ref, effective_start)"],
        ))

    want_default = f"('{prefix}'::text || lpad((nextval('{seq}'::regclass))::text, 8, '0'::text))"
    cur_default = _dealref_default(cur, table)
    if cur_default is None or "lpad" not in (cur_default or ""):
        steps.append((
            f"set deal_ref DEFAULT -> {prefix} + lpad(nextval('{seq}'),8)",
            [f"ALTER TABLE {table} ALTER COLUMN deal_ref SET DEFAULT "
             f"('{prefix}' || lpad(nextval('{seq}')::text, 8, '0'))"],
        ))

    print(f"\n===== {table} =====")
    if not steps:
        print("  already migrated — nothing to do.")
    for desc, _ in steps:
        print(f"  [ ] {desc}")

    if not apply or not steps:
        return

    for _, sqls in steps:
        for sql in sqls:
            cur.execute(sql)

    # Optional: floor the id sequence so new rows start at a chosen number
    # (e.g. stagger prod into a higher range). Never lowers below the rows
    # we just back-filled.
    if id_start is not None:
        cur.execute(f"SELECT max(id) FROM {table}")
        max_id = cur.fetchone()[0] or 0
        floor = max(id_start, max_id + 1)
        cur.execute(f"SELECT setval('{id_seq}', %s, false)", (floor,))
        print(f"  id sequence floored: next id -> {floor}")
    print("  applied.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="execute (default is a read-only dry-run)")
    ap.add_argument("--id-start", type=int, default=None,
                    help="floor the id sequence so the NEXT id is at least this")
    args = ap.parse_args()

    c = _load_creds()
    conn = psycopg2.connect(
        host=c["host"], port=int(c.get("port", "5432")), dbname=c["database"],
        user=c["username"], password=c["password"], connect_timeout=15,
    )
    print(f"DB: {c['database']} @ {c['host']}   mode: {'APPLY' if args.apply else 'DRY-RUN'}")
    try:
        for table, (prefix, seq) in TABLES.items():
            with conn:  # one transaction per table
                with conn.cursor() as cur:
                    migrate_table(cur, table, prefix, seq, args.id_start, args.apply)
    finally:
        conn.close()
    if not args.apply:
        print("\n(dry-run) nothing written. Re-run with --apply.")


if __name__ == "__main__":
    main()
