"""Hourly Uniswap v4 LP balance snapshot runner — isolated CronJob.

Runs in its OWN CronJob (helm_values/cron/uniswap-lp-snapshots.yaml) rather
than as a task inside snapshot_all.py, because `venue-snapshots` deploys to
BOTH environments and this collector is UAT-only for now (it writes the LP rows
the 8041 recon board reads, and that board lives in UAT).

Writes balance rows → middle_office.tq_hist_balance_mo, reusing snapshot_all.run
for the shared connection, per-task isolation and summary logging — the same
shape snapshot_bitstamp.py uses.

Run
---
    python scripts/snapshot_uniswap_lp.py --dry-run
    python scripts/snapshot_uniswap_lp.py
"""
from __future__ import annotations

import argparse
import logging

import snapshot_all
import stream_uniswap_lp_balance

log = logging.getLogger("snapshot_uniswap_lp")

# (label, module). Same snap_once(conn, dry_run) shape as every other venue.
# Balance only — there is no position collector for LPs; the decomposed
# amounts ARE the balance.
TASKS = [
    ("uniswap_lp.balance", stream_uniswap_lp_balance),
]


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Hourly Uniswap v4 LP snapshot runner (isolated CronJob)"
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch + print but don't INSERT")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    failed = snapshot_all.run(args.dry_run, tasks=TASKS)
    raise SystemExit(1 if failed == len(TASKS) else 0)


if __name__ == "__main__":
    main()
