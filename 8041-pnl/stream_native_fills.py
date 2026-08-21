"""Native Core fills collector -> trades_spot_avgcost (avg-cost, forward only).

Native's userFills retention is ~10k blocks = ~8.3 MINUTES (50 ms/block), and
there is no fill history or cost basis to backfill (see native_fills.py). So this
collector must run CONTINUOUSLY at a short interval to accumulate every fill into
trades_spot_avgcost; from then on the 8041 PnL picks up the Native legs and folds
exact avg-cost / realized. An hourly cadence would miss ~52 of every 60 minutes.

  python stream_native_fills.py --once --dry-run      # inspect, no writes
  python stream_native_fills.py --once                # one pull + insert
  python stream_native_fills.py --interval 120        # run continuously (default 2 min)

Each cycle: pull the live window, resolve side via orderStatus, fold each leg
onto its stored avg-cost tip, and insert new fills (idempotent on
(venue, instrument, external_trade_id, source); self-heals out-of-order folds).
"""
from __future__ import annotations
import argparse
import logging
import signal
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
import avgcost_db as adb            # noqa: E402
import native_fills as nf          # noqa: E402

WINDOW_MINUTES = nf.WINDOW * nf.BLOCK_MS / 1000 / 60
log = logging.getLogger("stream_native_fills")


def snap_once(conn, dry_run):
    legs = nf.native_legs()
    if not legs:
        log.info("no fills in the live window")
        return 0
    total = 0
    for leg, fills in legs:
        inst = leg["instrument"]
        if dry_run:
            netq = sum((f["signed_qty"] for f in fills), nf.D(0))
            log.info(f"DRY {inst:26s} {len(fills):3d} fills  net_qty={float(netq):+.4f}")
            continue
        ins, fresh, reason = adb.ingest_leg(conn, leg, fills)
        tag = f"  [SELF-HEALED: {reason}]" if reason else ""
        log.info(f"{inst:26s} +{ins} new (of {fresh} fresh, {len(fills)} pulled){tag}")
        total += ins
    return total


def main():
    ap = argparse.ArgumentParser(description="Native Core fills collector -> trades_spot_avgcost")
    ap.add_argument("--interval", type=int, default=120,
                    help="poll seconds (default 120; MUST stay well under the "
                         f"~{WINDOW_MINUTES:.0f} min retention window or fills are lost)")
    ap.add_argument("--once", action="store_true", help="one pull and exit")
    ap.add_argument("--dry-run", action="store_true", help="print, do not write")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    if not args.once and args.interval > WINDOW_MINUTES * 60 * 0.6:
        log.warning(f"interval {args.interval}s is close to the ~{WINDOW_MINUTES:.1f} min "
                    "retention window — fills may be missed; use a shorter interval")

    conn = None if args.dry_run else adb.connect()
    stop = {"flag": False}

    def handle(*_):
        stop["flag"] = True
    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(s, handle)
        except (OSError, ValueError):
            pass

    try:
        if args.once:
            snap_once(conn, args.dry_run)
            return
        log.info(f"polling every {args.interval}s (window ~{WINDOW_MINUTES:.1f} min)")
        while not stop["flag"]:
            try:
                snap_once(conn, args.dry_run)
            except Exception as e:
                log.error(f"snap failed: {e}")
            for _ in range(args.interval * 10):
                if stop["flag"]:
                    break
                time.sleep(0.1)
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()
