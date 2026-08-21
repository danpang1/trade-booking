"""Four-phase 8041 run: refresh the DB, compute from saved trades, mark Native,
then the MTD split.

Phase 1 — pull + fold + save ALL venue trades into trades_spot_avgcost
          (`pnl_8041_daily.py --ingest-only`).
Phase 2 — compute the DAILY PnL from the STORED trades (no re-pull) + the
          full-account recon (`pnl_8041_daily.py --no-pull --recon`).
Phase 3 — Native Core (TRADING_01@NATIVECORE) snapshot mark-to-market for the
          same COB day (`native_pnl_snapshot.py --date <COB>`).
Phase 4 — month-to-date PnL with a daily breakdown, split Dinari vs Native
          (`mtd_split.py --date <COB>`); inception .. COB.

So every run prints FOUR tables: DAILY PnL, FULL-ACCOUNT RECON, NATIVE MTM, and
the DINARI-vs-NATIVE daily + MTD split.

Any extra CLI args (e.g. --date, --mark) are forwarded to phases 1-2; phases 3-4
get only --date (neither takes --mark). Phases 3-4 are non-fatal — a missing
Native snapshot (incomplete day) won't abort the run.

  python run_with_db_trades.py --date 2026-06-17
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
DAILY = REPO / "pnl_8041_daily.py"
NATIVE = REPO / "native_pnl_snapshot.py"
MTD_SPLIT = REPO / "mtd_split.py"


def run_phase(label, script, extra, fatal=True):
    print(f"\n{'=' * 108}\n# {label}\n{'=' * 108}", flush=True)
    result = subprocess.run([sys.executable, str(script)] + extra)
    if result.returncode != 0:
        msg = "aborting." if fatal else "continuing (non-fatal)."
        print(f"\n[{label}] FAILED (exit {result.returncode}) — {msg}")
        if fatal:
            sys.exit(result.returncode)


def _date_arg(passthrough):
    """The --date value from the passthrough args (None if absent)."""
    for i, a in enumerate(passthrough):
        if a == "--date" and i + 1 < len(passthrough):
            return passthrough[i + 1]
        if a.startswith("--date="):
            return a.split("=", 1)[1]
    return None


def main():
    passthrough = sys.argv[1:]   # e.g. --date 2026-06-17 [--mark ...]
    run_phase("PHASE 1/4 — refresh DB (pull + fold + save all trades)",
              DAILY, passthrough + ["--ingest-only"])
    run_phase("PHASE 2/4 — PnL from stored trades + recon",
              DAILY, passthrough + ["--no-pull", "--recon"])
    date = _date_arg(passthrough)
    native_args = ["--date", date] if date else []
    run_phase("PHASE 3/4 — Native Core snapshot mark-to-market",
              NATIVE, native_args, fatal=False)
    run_phase("PHASE 4/4 — MTD PnL split (Dinari vs Native) + daily breakdown",
              MTD_SPLIT, native_args, fatal=False)
    print(f"\n{'=' * 108}\nDone: trades refreshed in trades_spot_avgcost; PnL "
          "computed from the stored trades; recon ran on live venue data; "
          "Native Core marked to HL perp index; MTD split printed.")


if __name__ == "__main__":
    main()
