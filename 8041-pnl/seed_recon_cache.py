"""Seed recon_day_cache from the latest published recon_runs payload.

A full rebuild costs ~4.5h, and one has just produced a complete 54-day payload
— so the cache is seeded from that rather than paying for a second identical
pass. This is only legitimate because the code edits made DURING that run
(cache wiring, CLI flags, log text) cannot move a number; the one edit that
could — the asset_map fix — landed BEFORE the run started, so the published
payload already reflects it.

If that assumption is ever false for a given run, don't seed: run
`recon_dashboard.py --force` and let it recompute honestly.

  python seed_recon_cache.py [--dry-run]
"""
from __future__ import annotations

import json
import sys

import avgcost_db
import recon_cache


def latest_payload():
    conn = avgcost_db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, generated_at, payload FROM recon_runs "
                        "ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        raise SystemExit("no recon_runs rows to seed from")
    rid, gen, payload = row
    if isinstance(payload, str):
        payload = json.loads(payload)
    return rid, gen, payload


def main():
    rid, gen, payload = latest_payload()
    days = payload.get("days") or []
    partial = payload.get("partial")
    print(f"recon_runs id={rid} generated={gen} days={len(days)} "
          f"partial={partial}")
    if partial:
        raise SystemExit("run is still PARTIAL — wait for it to finish before "
                         "seeding, or the cache captures half a board")
    if not days:
        raise SystemExit("payload has no days")
    print(f"span: {days[0]['day']} .. {days[-1]['day']}")
    if "--dry-run" in sys.argv:
        print("(dry run — nothing written)")
        return
    n = recon_cache.save(days)
    print(f"seeded {n} days at sig {recon_cache.code_sig()}")


if __name__ == "__main__":
    main()
