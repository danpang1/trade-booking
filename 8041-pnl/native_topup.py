"""Top up Native trades in trades_spot_avgcost from the CSV∪ClickHouse union.

  python native_topup.py

Idempotent (existing external ids skipped). CSV is frozen history; new fills
arrive via the ClickHouse execution collector. Used by run_cob_report.bat.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import avgcost_db as adb  # noqa: E402
from native_trades_source import native_trade_legs  # noqa: E402


def main():
    legs, n_csv, n_ch = native_trade_legs()
    print(f"native union: {n_csv} csv + {n_ch} ch-only fills")
    conn = adb.connect()
    try:
        for leg, fills in legs:
            ins, fresh, reason = adb.ingest_leg(conn, leg, fills)
            if ins or reason:
                tag = f"  [refolded: {reason}]" if reason else ""
                print(f"  {leg['instrument']:26} +{ins} new (of {fresh} fresh){tag}")
    finally:
        conn.close()
    print("native top-up done")


if __name__ == "__main__":
    main()
