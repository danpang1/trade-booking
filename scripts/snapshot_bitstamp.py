"""Hourly Bitstamp balance + position snapshot runner — isolated CronJob.

Bitstamp needs an API key (Vault-injected in prod via scripts/gw_creds.py).
Running it in its OWN CronJob (helm_values/cron/bitstamp-snapshots.yaml) means
a credential / Vault-agent issue can only fail this job — it can never break the
public-venue snapshots (Native / Lighter / Phoenix) run by snapshot_all.py.

Writes balance → middle_office.tq_hist_balance_mo and position →
tq_hist_position_mo via a single shared connection, reusing snapshot_all.run for
the per-task isolation + summary logging. If the key is absent the streamers
warn and self-skip (0 rows), so a not-yet-provisioned key is not a hard failure.

Run
---
    python scripts/snapshot_bitstamp.py --dry-run
    python scripts/snapshot_bitstamp.py
"""
from __future__ import annotations

import argparse
import logging

import snapshot_all
import stream_bitstamp
import stream_bitstamp_balance

log = logging.getLogger("snapshot_bitstamp")

# (label, module). Balance before position. Same snap_once(conn, dry_run) shape.
TASKS = [
    ("bitstamp.balance", stream_bitstamp_balance),
    ("bitstamp.position", stream_bitstamp),
]


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Hourly Bitstamp snapshot runner (isolated CronJob)"
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
