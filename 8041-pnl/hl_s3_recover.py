"""Pull the S3 fills for each day the audit flagged, ready for staging.

One JSON per day (hl_s3_fills_{YYYYMMDD}.json), so a partial run loses
nothing and each day can be staged/verified independently. Reuses the audit's
parallel hour fetch and its shared cost meter (the $100 cap still applies).

Read-only against the store — writes files only. Staging and promotion stay
separate, deliberate steps.

  python hl_s3_recover.py hl_recover_days.txt [--workers 8]
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import hl_s3_audit as audit
import hl_s3_fills as s3m

REPO = Path(__file__).resolve().parent


def pull_day(s3, ymd, workers):
    fills, absent = [], []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for h, res in zip(range(24), ex.map(
                lambda h: audit.hour_fills(s3, ymd, h), range(24))):
            if res is None:
                absent.append(h)
            else:
                fills.extend(res)
    return fills, absent


def main():
    if "--dates" in sys.argv:
        i = sys.argv.index("--dates") + 1
        days = [a for a in sys.argv[i:] if not a.startswith("--")]
    else:
        days = [s.strip() for s in
                Path(sys.argv[1]).read_text(encoding="utf-8").split()
                if s.strip()]
    workers = 8
    if "--workers" in sys.argv:
        workers = int(sys.argv[sys.argv.index("--workers") + 1])
    s3 = s3m.client()
    print(f"pulling {len(days)} days (~${len(days) * 0.114:.2f} est)")
    for i, day in enumerate(days, 1):
        ymd = datetime.strptime(day, "%Y-%m-%d").strftime("%Y%m%d")
        out = REPO / f"hl_s3_fills_{ymd}.json"
        if out.exists():
            print(f"[{i}/{len(days)}] {day}: already pulled, skipping")
            continue
        t0 = time.time()
        try:
            fills, absent = pull_day(s3, ymd, workers)
        except RuntimeError as e:            # cost cap
            print(f"STOPPED: {e}")
            break
        out.write_text(json.dumps(fills, indent=1), encoding="utf-8")
        usd = (audit._cost["bytes"] / 1e9 * s3m.GB_PRICE
               + audit._cost["gets"] * s3m.GET_PRICE)
        note = f"  ABSENT HOURS {absent}" if absent else ""
        print(f"[{i}/{len(days)}] {day}: {len(fills):>6} fills -> {out.name} "
              f"({time.time() - t0:.0f}s, ~${usd:.2f}){note}", flush=True)
    print("RECOVER_PULL_DONE")


if __name__ == "__main__":
    main()
