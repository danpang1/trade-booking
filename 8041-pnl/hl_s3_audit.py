"""Audit every HL trading day against the S3 node-data archive.

Answers one question per day: does the store hold every fill the chain
recorded? S3 is the only complete source — the venue API retains ~10k fills
and ClickHouse has its own collector outages — so a tid present in S3 and
absent from `trades_spot_avgcost` is a genuinely missing trade.

Also totals REAL FEES per day. ClickHouse has no fee column, so every
CH-sourced row carries fee 0; the gap between S3's fee total and the store's
is unrecorded cost.

Read-only: writes a JSON report, never touches the store. Promotion stays a
separate, deliberate step (stage -> verify -> promote).

Hours are fetched in parallel because each is a ~40 MB download and ~150 MB
of string scanning; sequential runs at ~5 min/day (7h for the full history).
The cost ledger is shared mutable state, so it is written under a lock.

  python hl_s3_audit.py 2026-05-06 2026-08-03 [--workers 8]
Resumable: days already in the report are skipped.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

import avgcost_db
import hl_s3_fills as s3m

REPO = Path(__file__).resolve().parent
REPORT = REPO / "hl_s3_audit.json"
_lock = threading.Lock()
_cost = {"bytes": 0, "gets": 0}


def _meter(nbytes):
    with _lock:
        _cost["bytes"] += nbytes
        _cost["gets"] += 1
        usd = (_cost["bytes"] / 1e9 * s3m.GB_PRICE
               + _cost["gets"] * s3m.GET_PRICE)
        if usd >= s3m.COST_CAP_USD:
            raise RuntimeError(f"COST CAP hit: ~${usd:.2f}")
        return usd


def hour_fills(s3, ymd, hour):
    """Our fills for one hour, or None if the object is absent."""
    import lz4.frame
    key = f"node_fills_by_block/hourly/{ymd}/{hour}"
    for suffix in (".lz4", ""):
        try:
            r = s3.get_object(Bucket=s3m.BUCKET, Key=key + suffix,
                              RequestPayer="requester")
            raw = r["Body"].read()
            _meter(len(raw))
            data = (lz4.frame.decompress(raw) if suffix else raw).decode(
                "utf-8", errors="replace")
            out = []
            for ln in data.splitlines():
                # addresses in these files are lower-case already; skipping
                # .lower() on every line matters at ~150 MB/hour
                if not ln or s3m.USER not in ln:
                    continue
                out.extend(s3m.extract_fills(json.loads(ln)))
            return out
        except s3.exceptions.NoSuchKey:
            continue
    return None


def store_day(conn, day):
    """(tids, total fee_usd, fee_usd on USDC-denominated fills only).

    The third value is what compares like-for-like against S3's USDC fee
    total; the second includes fees charged in SPCXD etc., already priced
    into USD by the ingest."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT external_trade_id, COALESCE(fee_usd, 0),
                   COALESCE(fee_asset, 'USDC')
            FROM trades_spot_avgcost
            WHERE venue = 'HYPERLIQUID'
              AND trade_date >= %s AND trade_date < %s
        """, (day, day + timedelta(days=1)))
        rows = cur.fetchall()
    return ({r[0] for r in rows},
            sum(D(str(r[1])) for r in rows),
            sum(D(str(r[1])) for r in rows if r[2] == "USDC"))


def audit_day(s3, conn, day, workers):
    ymd = day.strftime("%Y%m%d")
    fills, missing_hours = [], []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for h, res in zip(range(24), ex.map(
                lambda h: hour_fills(s3, ymd, h), range(24))):
            if res is None:
                missing_hours.append(h)
            else:
                fills.extend(res)
    s3_ids = {str(f["tid"]) for f in fills}
    # Fees are denominated in feeToken, NOT always USDC: HL spot charges the
    # fee in the RECEIVED token, so a raw `fee` of 1.30 on an SPCXD fill is
    # 1.30 SPCXD (~$270), not $1.30. Summing raw numbers across tokens is
    # meaningless — keep them separate and let the caller price non-USDC.
    fee_by_token = {}
    for f in fills:
        tok = f.get("feeToken") or "USDC"
        amt = D(str(f.get("fee") or 0)) + D(str(f.get("deployerFee") or 0))
        fee_by_token[tok] = fee_by_token.get(tok, D(0)) + amt
    s3_fee = fee_by_token.get("USDC", D(0))     # USDC-denominated only
    store_ids, store_fee, store_fee_usdc = store_day(conn, day)
    miss = s3_ids - store_ids
    by_coin = {}
    for f in fills:
        if str(f["tid"]) in miss:
            by_coin[f["coin"]] = by_coin.get(f["coin"], 0) + 1
    return {
        "day": day.strftime("%Y-%m-%d"),
        "s3_fills": len(s3_ids), "store_fills": len(store_ids),
        "missing": len(miss), "extra_in_store": len(store_ids - s3_ids),
        "s3_fee_usdc": float(s3_fee), "store_fee_usd": float(store_fee),
        "fee_gap": float(s3_fee - store_fee),
        "s3_fee_by_token": {k: float(v) for k, v in fee_by_token.items()},
        "store_fee_usdc_only": float(store_fee_usdc),
        "missing_by_coin": dict(sorted(by_coin.items(), key=lambda x: -x[1])),
        "absent_hours": missing_hours,
    }


def main():
    workers = 8
    if "--workers" in sys.argv:
        workers = int(sys.argv[sys.argv.index("--workers") + 1])
    # --days-file targets only the days that actually carry recon breaks,
    # which is where the answer is and cuts the spend ~2x vs the full history
    if "--days-file" in sys.argv:
        path = Path(sys.argv[sys.argv.index("--days-file") + 1])
        wanted = [datetime.strptime(s.strip(), "%Y-%m-%d").replace(
            tzinfo=timezone.utc)
            for s in path.read_text(encoding="utf-8").split() if s.strip()]
    else:
        d0 = datetime.strptime(sys.argv[1], "%Y-%m-%d").replace(
            tzinfo=timezone.utc)
        d1 = datetime.strptime(sys.argv[2], "%Y-%m-%d").replace(
            tzinfo=timezone.utc)
        wanted = []
        while d0 <= d1:
            wanted.append(d0)
            d0 += timedelta(days=1)
    done = {}
    if REPORT.exists():
        done = {r["day"]: r for r in json.loads(
            REPORT.read_text(encoding="utf-8"))}
        print(f"resuming: {len(done)} days already audited")
    s3 = s3m.client()
    conn = avgcost_db.connect()
    todo = [d for d in wanted if d.strftime("%Y-%m-%d") not in done]
    print(f"auditing {len(todo)} days (~${len(todo) * 0.114:.2f} est)")
    try:
        for i, day in enumerate(todo, 1):
            key = day.strftime("%Y-%m-%d")
            t0 = time.time()
            try:
                rec = audit_day(s3, conn, day, workers)
            except RuntimeError as e:      # cost cap
                print(f"STOPPED: {e}")
                break
            done[key] = rec
            usd = (_cost["bytes"] / 1e9 * s3m.GB_PRICE
                   + _cost["gets"] * s3m.GET_PRICE)
            flag = "  <-- MISSING" if rec["missing"] else ""
            print(f"[{i}/{len(todo)}] {key}  s3={rec['s3_fills']:>6} "
                  f"store={rec['store_fills']:>6} miss={rec['missing']:>5} "
                  f"feegap={rec['fee_gap']:>9.2f} "
                  f"({time.time()-t0:.0f}s, ~${usd:.2f}){flag}", flush=True)
            REPORT.write_text(json.dumps(sorted(done.values(),
                                                key=lambda r: r["day"]),
                                         indent=1), encoding="utf-8")
    finally:
        conn.close()
    rows = sorted(done.values(), key=lambda r: r["day"])
    tm = sum(r["missing"] for r in rows)
    tf = sum(r["fee_gap"] for r in rows)
    print(f"\n=== {len(rows)} days audited ===")
    print(f"total missing fills : {tm:,}")
    print(f"total fee gap       : {tf:,.2f} USDC")
    print(f"cost                : ~${_cost['bytes']/1e9*s3m.GB_PRICE:.2f}")
    print(f"report              : {REPORT}")


if __name__ == "__main__":
    main()
