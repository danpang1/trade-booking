"""Hourly venue balance + position snapshot runner.

Invoked by the `venue-snapshots` CronJob (helm_values/cron/venue-snapshots.yaml)
once per UTC hour. Snaps every public venue's balance and position into the MO
Postgres tables (tq_hist_balance_mo / tq_hist_position_mo) using a single shared
connection.

Each task is isolated: a failure in one venue (e.g. a transient API blip) is
logged and the remaining venues still record. The process exits non-zero only
if EVERY task fails, so a single-venue outage doesn't mark the whole CronJob
failed.

Venues: Native Core, Lighter, Phoenix (all public, read-only APIs). Bitget is
intentionally excluded until its API-key Secret is wired.

Run
---
    python scripts/snapshot_all.py --dry-run
    python scripts/snapshot_all.py
"""
from __future__ import annotations

import argparse
import logging

import mo_db

import stream_lighter
import stream_lighter_balance
import stream_native
import stream_native_balance
import stream_phoenix
import stream_phoenix_balance

log = logging.getLogger("snapshot_all")

# (label, module). Each module exposes snap_once(conn, dry_run) -> int rows.
# Balance task runs before its position task per venue.
TASKS = [
    ("native.balance", stream_native_balance),
    ("native.position", stream_native),
    ("lighter.balance", stream_lighter_balance),
    ("lighter.position", stream_lighter),
    ("phoenix.balance", stream_phoenix_balance),
    ("phoenix.position", stream_phoenix),
]


def run(dry_run: bool) -> int:
    """Run every task with per-task isolation. Returns the failed-task count."""
    conn = None if dry_run else mo_db.connect()
    ok, failed, total_rows = 0, 0, 0
    try:
        for label, mod in TASKS:
            try:
                n = mod.snap_once(conn, dry_run) or 0
                total_rows += n
                ok += 1
                log.info(f"[{label}] OK rows={n}")
            except Exception as e:
                failed += 1
                log.error(f"[{label}] FAILED: {e}")
    finally:
        if conn is not None:
            conn.close()
    log.info(
        f"summary: tasks_ok={ok} tasks_failed={failed} rows_written={total_rows}"
    )
    return failed


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Hourly venue snapshot runner (all public venues)"
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch + print but don't INSERT")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    failed = run(args.dry_run)
    raise SystemExit(1 if failed == len(TASKS) else 0)


if __name__ == "__main__":
    main()
