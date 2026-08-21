"""Per-day cache for the hourly recon board, so a daily run recomputes only
what actually changed instead of replaying the whole window.

Why a cache at all: `publish_db` writes the ENTIRE window as one JSONB row and
the API serves the latest row, so a short rebuild would publish a short board
and the rest of the history would vanish. The cache lets us recompute a suffix
and re-assemble the full payload before publishing.

Why a SUFFIX and not a scattered set of days: a change at day D does not stay
local. `positions_at_cutoff` chains prev-EOD -> EOD, off-book gaps are
cumulative levels, and avg-cost folding is a running replay — so a back-dated
fill on D moves every day after it. Recomputing D..today is the honest minimum,
and it is also why a repair deep in history correctly degrades to a full
rebuild rather than quietly patching one day.

Staleness guards, in order of how they fire:
  1. code signature — any edit to the files that shape the numbers invalidates
     the whole cache (today's `asset_map` fix genuinely needed every day re-run;
     a cache that ignored it would have served wrong history forever)
  2. data watermark — new rows in fills / transfers / snapshots whose event
     date is older than the tip drag the recompute point back to that date
  3. floor — the last N days are always recomputed regardless

Usage from recon_dashboard.main(); see `earliest_dirty`.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import avgcost_db

REPO = Path(__file__).resolve().parent

# Files whose contents change what a day's numbers ARE. An edit to any of them
# invalidates every cached day. Keep this list honest — a file that shapes the
# output but is missing here is exactly how a cache serves stale history.
CODE_FILES = (
    "recon_dashboard.py",
    "asset_map.py",
    "equity_marks.py",
    "account_recon.py",
    "hl_flows.py",
    "chain_transfers.py",
)

DDL = """
CREATE TABLE IF NOT EXISTS recon_day_cache (
    day         DATE PRIMARY KEY,
    payload     JSONB NOT NULL,
    code_sig    TEXT NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def code_sig():
    """Hash of every computation-shaping source file (missing files skipped)."""
    h = hashlib.sha256()
    for name in CODE_FILES:
        p = REPO / name
        if p.exists():
            h.update(name.encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def _ensure(cur):
    cur.execute(DDL)


def state():
    """(last computed_at, cached code_sig, n cached days) — Nones if empty."""
    conn = avgcost_db.connect()
    try:
        with conn.cursor() as cur:
            _ensure(cur)
            cur.execute("SELECT max(computed_at), count(*) "
                        "FROM recon_day_cache")
            last, n = cur.fetchone()
            cur.execute("SELECT DISTINCT code_sig FROM recon_day_cache")
            sigs = {r[0] for r in cur.fetchall()}
        conn.commit()
        return last, (sigs.pop() if len(sigs) == 1 else None), n
    finally:
        conn.close()


def _min_date(cur, sql, since):
    cur.execute(sql, (since,))
    row = cur.fetchone()
    return row[0] if row and row[0] else None


def earliest_dirty(span_start, floor_days=2, verbose=True):
    """First day that must be recomputed, or `span_start` for a full rebuild.

    Returns (day, reason). Never returns a day later than today-floor_days, so
    the open tip and the day behind it are always re-run (marks finalize, late
    fills land, unrealized moves)."""
    today = datetime.now(timezone.utc).date()
    floor = today - timedelta(days=floor_days)
    last, sig, n = state()
    if not n:
        return span_start, "cache empty"
    if sig != code_sig():
        return span_start, "code changed (recon logic edited)"
    if last is None:
        return span_start, "no cache watermark"

    conn = avgcost_db.connect()
    try:
        with conn.cursor() as cur:
            probes = (
                ("fills", "SELECT min(trade_date::date) FROM "
                          "trades_spot_avgcost WHERE ingested_at > %s"),
                ("transfers", "SELECT min(event_time::date) FROM "
                              "venue_transfers WHERE created_at > %s"),
                ("balance snaps", "SELECT min(sync_ts::date) FROM "
                                  "tq_hist_balance_mo WHERE record_ts > %s"),
                ("position snaps", "SELECT min(sync_ts::date) FROM "
                                   "tq_hist_position_mo WHERE record_ts > %s"),
            )
            hits = []
            for label, sql in probes:
                d = _min_date(cur, sql, last)
                if d:
                    hits.append((d, label))
    finally:
        conn.close()

    day, reason = floor, f"floor ({floor_days}d)"
    if hits:
        oldest, label = min(hits)
        if oldest < day:
            day, reason = oldest, f"back-dated {label}"
    if verbose and hits:
        print("[cache] new rows since last run: " + ", ".join(
            f"{label} from {d}" for d, label in sorted(hits)))
    return max(span_start, day), reason


def digest(day_payload):
    """Compact fingerprint of a day's NUMBERS, for cache-vs-recompute drift.

    Deliberately coarse — hourly gross/net and the EOD break count. It exists
    to answer 'did the cache serve something the code no longer produces?',
    which is the failure mode a cache can hide indefinitely."""
    gross = net = 0.0
    nbrk = 0
    for h in day_payload.get("hours") or []:
        for c in (h.get("cols") or {}).values():
            if not c or c.get("status") != "ok":
                continue
            gross += abs(float(c.get("gross") or 0))
            net += float(c.get("net") or 0)
            nbrk += int(c.get("nbrk") or 0)
    pos = day_payload.get("positions") or {}
    npos = sum(len(a.get("inventory") or [])
               for a in (pos.get("accounts") or []))
    return (round(gross, 2), round(net, 2), nbrk, npos)


def compare(fresh_days, verbose=True):
    """Diff freshly computed days against what the cache held. Returns the
    list of days that disagree (empty = cache was faithful)."""
    conn = avgcost_db.connect()
    try:
        with conn.cursor() as cur:
            _ensure(cur)
            cur.execute("SELECT day, payload FROM recon_day_cache")
            old = {str(d): p for d, p in cur.fetchall()}
    finally:
        conn.close()
    drift = []
    for d in fresh_days:
        if d["day"] not in old:
            continue
        a, b = digest(old[d["day"]]), digest(d)
        if a != b:
            drift.append((d["day"], a, b))
    if verbose:
        if not old:
            print("[cache] nothing cached to compare against")
        elif drift:
            print(f"[cache] DRIFT on {len(drift)} day(s) — the cache was "
                  "serving numbers the current code does not reproduce:")
            for day, a, b in drift[:20]:
                print(f"  {day}: cached gross/net/nbrk/rows={a} -> fresh={b}")
        else:
            print(f"[cache] verified: {len(fresh_days)} recomputed days match "
                  "what the cache was serving")
    return drift


def load_before(day):
    """Cached day payloads with day < `day`, oldest first."""
    conn = avgcost_db.connect()
    try:
        with conn.cursor() as cur:
            _ensure(cur)
            cur.execute("SELECT payload FROM recon_day_cache "
                        "WHERE day < %s ORDER BY day", (day,))
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def save(days_out, sig=None):
    """Upsert freshly computed day payloads. `days_out` = build()'s day dicts."""
    sig = sig or code_sig()
    conn = avgcost_db.connect()
    try:
        with conn.cursor() as cur:
            _ensure(cur)
            for d in days_out:
                cur.execute("""
                    INSERT INTO recon_day_cache (day, payload, code_sig,
                                                 computed_at)
                    VALUES (%s, %s, %s, now())
                    ON CONFLICT (day) DO UPDATE
                       SET payload = EXCLUDED.payload,
                           code_sig = EXCLUDED.code_sig,
                           computed_at = now()
                """, (d["day"], json.dumps(d), sig))
        conn.commit()
        return len(days_out)
    finally:
        conn.close()


def drop_all():
    conn = avgcost_db.connect()
    try:
        with conn.cursor() as cur:
            _ensure(cur)
            cur.execute("DELETE FROM recon_day_cache")
        conn.commit()
    finally:
        conn.close()


def restamp():
    """Accept the current code as equivalent to what the cache was built with.

    The signature is deliberately blunt — it hashes whole files, so a CSS tweak
    inside recon_dashboard.py invalidates 54 days of cache the same as a
    changed formula would. Use this ONLY when you know the edit cannot move a
    number (styling, comments, logging). Getting it wrong means the board keeps
    serving history computed by the old logic, silently."""
    conn = avgcost_db.connect()
    try:
        with conn.cursor() as cur:
            _ensure(cur)
            cur.execute("UPDATE recon_day_cache SET code_sig = %s",
                        (code_sig(),))
            n = cur.rowcount
        conn.commit()
        return n
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    if "--restamp" in sys.argv:
        print(f"restamped {restamp()} cached days to sig {code_sig()}")
        sys.exit(0)
    if "--drop" in sys.argv:
        drop_all()
        print("cache cleared")
        sys.exit(0)
    last, sig, n = state()
    print(f"cached days : {n}")
    print(f"last run    : {last}")
    print(f"cached sig  : {sig}")
    print(f"current sig : {code_sig()}"
          + ("  <- MATCH" if sig == code_sig() else "  <- CHANGED (full "
             "rebuild on next run)"))
    if n:
        d, why = earliest_dirty(date(2026, 6, 9))
        print(f"would rebuild from {d}  ({why})")
