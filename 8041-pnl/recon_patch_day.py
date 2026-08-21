"""Recompute ONE day (or a few) and splice it into the published board.

The day-by-day companion to the full rebuild: after repairing entries for a
specific date, this recomputes just that date through the SAME build() as the
full rebuild — marks, EOD positions, everything — upserts it into the per-day
cache, and republishes the merged board. Minutes, not hours.

Honesty note: the other cached days keep whatever the last rebuild computed.
A change whose effect is NOT local to the patched day (a back-dated fill also
moves every later day's cumulative positions) still needs the suffix rebuild —
this tool is for the day-by-day entry-verification walk, where each day is
inspected and re-stamped one at a time, ending with a final --force rebuild
to verify the whole window.

  python recon_patch_day.py 2026-06-11
  python recon_patch_day.py 2026-06-11 2026-06-12 --no-publish
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone

import recon_cache as cache
import recon_dashboard as rd


def patch_day(day_str):
    d0 = datetime.strptime(day_str, "%Y-%m-%d")
    data = rd.build(1, end_date=d0 + timedelta(days=1))
    fresh = [d for d in data["days"] if d["day"] == day_str]
    if not fresh:
        raise SystemExit(f"build() returned no payload for {day_str} "
                         f"(got {[d['day'] for d in data['days']]})")
    cache.save(fresh)
    return fresh[0]


def republish():
    days = cache.load_before(date(9999, 1, 1))       # the whole cached board
    if not days:
        raise SystemExit("cache is empty — nothing to publish")
    rd._tag_snap_gaps(days)
    now = datetime.now(timezone.utc)
    payload = {
        "generated": now.replace(tzinfo=None).isoformat(
            timespec="seconds") + "Z",
        "accounts": [{"id": a, "label": rd.COL_LABEL[a]}
                     for a in rd.ACCOUNTS],
        "thresholds": {"ok": rd.TH_OK, "warn": rd.TH_WARN, "bad": rd.TH_BAD},
        "untracked": [], "partial": False, "days": days,
    }
    rd.publish_db(payload)
    print(f"[patch] republished board: {len(days)} days "
          f"({days[0]['day']} .. {days[-1]['day']})")


def main():
    days = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not days:
        raise SystemExit(__doc__)
    _, sig, n = cache.state()
    if n and sig is None:
        raise SystemExit("cache holds MIXED code signatures — run "
                         "'python recon_cache.py --restamp' (or a full "
                         "rebuild) first so the baseline is coherent")
    if n and sig != cache.code_sig():
        raise SystemExit(
            "cached days were built by DIFFERENT code than what is on disk.\n"
            "If the code edits cannot move historical numbers, accept the "
            "baseline first:  python recon_cache.py --restamp\n"
            "Otherwise a full rebuild is the honest path.")
    for day_str in days:
        datetime.strptime(day_str, "%Y-%m-%d")       # validate early
    for day_str in days:
        print(f"\n[patch] recomputing {day_str} ...")
        d = patch_day(day_str)
        g = cache.digest(d)
        print(f"[patch] {day_str}: gross={g[0]:,.2f} net={g[1]:,.2f} "
              f"breaks={g[2]} eod_rows={g[3]} — cached")
    if "--no-publish" not in sys.argv:
        republish()


if __name__ == "__main__":
    main()
