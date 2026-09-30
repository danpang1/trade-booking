"""Stamp counterparty_id on live rows that name a refdata counterparty but
carry no CID, across trades_cashflow / trades_spot / trades_loan.

Until 2026-09-30 the CID was set by the form only; anything booked through
the API (the Slack bot, imports, the CLI) arrived with counterparty_id NULL
even when the name was a valid refdata counterparty. The validator now
stamps it on every insert / amend (cashflow_db.stamp_counterparty); this
brings the existing rows in line.

Only rows whose name is an EXACT refdata name are touched. Free-text names
are listed and left alone -- they need a human to pick the right
counterparty and amend the deal.

    python fix_counterparty_ids.py           # dry run: counts + free-text list
    python fix_counterparty_ids.py --apply   # write the CIDs
    python fix_counterparty_ids.py --sql     # print the UPDATEs only

Reads MO_DB_* env vars, else the `# MO DB UAT` block in /.env (so point it
at prod with env vars, or hand --sql to SRE). Idempotent.
"""
from __future__ import annotations
import sys

import cashflow_db

TABLES = ("trades_cashflow", "trades_spot", "trades_loan")


def plan(cur, cps: dict) -> tuple[list[dict], list[dict]]:
    """(rows to stamp, free-text names) over the live, non-cancelled book."""
    fixes, free = [], []
    for t in TABLES:
        cur.execute(
            f"SELECT counterparty, count(*) FROM {t} "
            " WHERE effective_end IS NULL AND status <> 'CANCELLED' "
            "   AND counterparty_id IS NULL AND counterparty IS NOT NULL "
            "   AND counterparty !~ '^[0-9]+$' "
            " GROUP BY counterparty ORDER BY counterparty"
        )
        for name, n in cur.fetchall():
            if name in cps:
                fixes.append({"table": t, "name": name, "cid": cashflow_db.format_cid(cps[name]), "n": n})
            else:
                free.append({"table": t, "name": name, "n": n})
    return fixes, free


def as_sql(fixes: list[dict]) -> str:
    return "\n".join(
        f"UPDATE {f['table']} SET counterparty_id = '{f['cid']}' "
        f"WHERE effective_end IS NULL AND counterparty_id IS NULL "
        f"AND counterparty = '{f['name'].replace(chr(39), chr(39) * 2)}';  -- {f['n']} rows"
        for f in fixes
    )


def main(argv) -> int:
    apply = "--apply" in argv
    cps = cashflow_db._load_counterparties_map()
    conn = cashflow_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                fixes, free = plan(cur, cps)
                if "--sql" in argv:
                    print(as_sql(fixes) or "-- nothing to change")
                    return 0
                total = sum(f["n"] for f in fixes)
                print(f"rows to stamp: {total} across {len(fixes)} (table, name) pairs")
                for f in fixes:
                    print(f"  {f['table']:16s} {f['name']:40s} -> {f['cid']}  ({f['n']})")
                if free:
                    print(f"\nfree-text counterparties left alone: {sum(x['n'] for x in free)} rows")
                    for x in free:
                        print(f"  {x['table']:16s} {x['name']!r}  ({x['n']})")
                if not apply:
                    print("\ndry run; re-run with --apply to write")
                    return 0
                done = 0
                for f in fixes:
                    cur.execute(
                        f"UPDATE {f['table']} SET counterparty_id = %s "
                        " WHERE effective_end IS NULL AND counterparty_id IS NULL AND counterparty = %s",
                        (f["cid"], f["name"]),
                    )
                    done += cur.rowcount
                print(f"\nstamped {done} rows")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
