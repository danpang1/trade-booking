"""Set the trades_cashflow MCF deal-ref sequence (`trade_seq_cashflow`) so the
NEXT booked cashflow gets a chosen number.

MCF deal-refs are allocated as `MCF{nextval('trade_seq_cashflow'):08d}`
(see cashflow_insert.py). Booking from a low sequence after historical /
backfilled deals (which carry custom refs and don't advance the sequence)
would issue refs that sit *below* the historical range. This tool fast-
forwards the sequence so new bookings continue cleanly above them.

Historical rows are NEVER touched — only the sequence's next value changes.

Reads DB credentials from the `#MO DB UAT` block in /.env (same mechanism
as apply_schema_cashflow.py), or from MO_DB_* env vars.

Usage:
    # inspect (read-only) — show current sequence + max existing MCF:
    python scripts/set_cashflow_seq.py

    # apply — make the next booked cashflow MCF00002453:
    python scripts/set_cashflow_seq.py --next 2453 --apply

Refuses to apply if an existing deal_ref >= the target would collide,
unless --force is passed.
"""
from __future__ import annotations
import argparse
import os
import re
import sys
from pathlib import Path

import psycopg2

REPO = Path(__file__).resolve().parents[1]
ENV = REPO / ".env"
MCF_RE = re.compile(r"^MCF(\d{8})$")


def _load_creds() -> dict[str, str]:
    """Env vars (MO_DB_*) take precedence; .env `#MO DB UAT` block fallback."""
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


def main() -> None:
    ap = argparse.ArgumentParser(description="Set the MCF cashflow deal-ref sequence.")
    ap.add_argument("--next", type=int, default=2453,
                    help="numeric value for the NEXT MCF deal_ref (default 2453)")
    ap.add_argument("--apply", action="store_true",
                    help="actually write the change (default is a read-only dry-run)")
    ap.add_argument("--force", action="store_true",
                    help="apply even if an existing ref >= target would collide")
    args = ap.parse_args()
    target = args.next
    if target < 1:
        print("--next must be >= 1", file=sys.stderr)
        sys.exit(2)

    c = _load_creds()
    conn = psycopg2.connect(
        host=c["host"], port=int(c.get("port", "5432")), dbname=c["database"],
        user=c["username"], password=c["password"], connect_timeout=15,
    )
    conn.autocommit = False
    cur = conn.cursor()

    # Current sequence position. nextval would return last_value+1 once the
    # sequence has been called at least once (is_called=true), else last_value.
    cur.execute("SELECT last_value, is_called FROM trade_seq_cashflow")
    last_value, is_called = cur.fetchone()
    cur_next = last_value + 1 if is_called else last_value

    # Largest existing well-formed MCF deal_ref.
    cur.execute("SELECT deal_ref FROM trades_cashflow WHERE deal_ref ~ '^MCF[0-9]{8}$'")
    nums = [int(m.group(1)) for (ref,) in cur.fetchall() if (m := MCF_RE.match(ref))]
    max_existing = max(nums) if nums else 0

    print(f"DB                         : {c['database']} @ {c['host']}")
    print(f"current next deal_ref      : MCF{cur_next:08d}  (last_value={last_value}, is_called={is_called})")
    print(f"max existing MCF deal_ref  : MCF{max_existing:08d}")
    print(f"requested next deal_ref    : MCF{target:08d}")

    collision = max_existing >= target
    if collision:
        print(f"WARNING: existing MCF{max_existing:08d} >= target MCF{target:08d} "
              f"— applying risks duplicate deal-refs.")

    if not args.apply:
        print("\n(dry-run) nothing written. Re-run with --apply to set the sequence.")
        conn.rollback()
        return

    if collision and not args.force:
        print("\nrefusing to apply due to collision risk; pass --force to override.")
        conn.rollback()
        sys.exit(2)

    # setval(seq, target, false): last_value=target, is_called=false, so the
    # very next nextval() returns `target` exactly. Historical rows untouched.
    cur.execute("SELECT setval('trade_seq_cashflow', %s, false)", (target,))
    conn.commit()

    cur.execute("SELECT last_value, is_called FROM trade_seq_cashflow")
    lv, ic = cur.fetchone()
    new_next = lv + 1 if ic else lv
    print(f"\napplied — next booked cashflow will be MCF{new_next:08d}")


if __name__ == "__main__":
    main()
