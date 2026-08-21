"""Put REAL fees on HL fills that were ingested from ClickHouse with fee 0.

`production.execution` has no fee column, so every CH-sourced row lands with
`fee_amount = fee_usd = 0`. That is ~131k HL fills and ~$10.2k of unrecorded
cost — the largest known error in HL P&L, and the likely bulk of the
unexplained `xyz:USDC` residue.

This is an UPDATE, not an insert: `staged_repair` can only add fills, and the
rows already exist. Matching is by `external_trade_id` = the S3 `tid`, which
shares the venue API's id-space, so the join is exact rather than heuristic.

Fee = `fee` + `deployerFee`. The HIP-3 dex charges a deployer fee on top of
the standard one and both debit USDC; taking `fee` alone leaves the deployer
portion unexplained.

feeToken matters: HL spot charges the fee in the RECEIVED token, so a raw
`fee` of 1.30 on an SPCXD fill is 1.30 SPCXD (~$270), NOT $1.30. Non-USDC
fees are written to fee_amount/fee_asset but fee_usd is left alone unless a
price is available — silently treating them as dollars is how a -$253
phantom appeared in the first audit.

NOT only zero-fee rows (widened 2026-08-03): the venue API does not expose
`deployerFee` AT ALL — verified against live userFills — so every
API-sourced xyz fill understates its fee by the deployer portion (06-19:
741 fills, $1.66). Any stored HL row whose (fee_amount, fee_asset) differs
from the S3 truth is corrected, whatever its source. S3 is ground truth.

Changing a fee changes realized P&L, so every touched leg is refolded.

  python hl_fee_backfill.py [--dry-run] [--no-refold]
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from decimal import Decimal as D
from pathlib import Path

import avgcost_db

REPO = Path(__file__).resolve().parent


def s3_fees():
    """{tid: (fee_amount, fee_token)} from every hl_s3_fills_*.json on disk."""
    out = {}
    for p in sorted(glob.glob(str(REPO / "hl_s3_fills_*.json"))):
        for f in json.loads(Path(p).read_text(encoding="utf-8")):
            fee = D(str(f.get("fee") or 0)) + D(str(f.get("deployerFee") or 0))
            out[str(f["tid"])] = (fee, str(f.get("feeToken") or "USDC"))
    return out


def main():
    dry = "--dry-run" in sys.argv
    fees = s3_fees()
    print(f"[fees] {len(fees):,} fills with fee data across "
          f"{len(glob.glob(str(REPO / 'hl_s3_fills_*.json')))} S3 day-files")
    conn = avgcost_db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, external_trade_id, instrument, account, product,
                       quote_asset, source, fee_amount, fee_asset
                FROM trades_spot_avgcost
                WHERE venue = 'HYPERLIQUID'
            """)
            rows = cur.fetchall()
        print(f"[fees] {len(rows):,} HL rows in the store")
        upd, legs, by_token = [], set(), {}
        unmatched = zero_fixed = corrected = 0
        for rid, tid, inst, acct, prod, quote, src, cur_fee, cur_tok in rows:
            hit = fees.get(str(tid))
            if not hit:
                # only a problem when the row has no fee at all (CH-sourced
                # day never pulled from S3); API rows carry their own fee
                if src == "clickhouse" and D(str(cur_fee or 0)) == 0:
                    unmatched += 1
                continue
            fee, tokn = hit
            was = D(str(cur_fee or 0))
            if abs(was - fee) < D("1e-12") and (cur_tok or "USDC") == tokn:
                continue                              # already exact
            if was == 0:
                zero_fixed += 1
            else:
                corrected += 1                        # e.g. deployerFee gap
            by_token[tokn] = by_token.get(tokn, D(0)) + (fee - was)
            # fee_usd only when the fee IS dollars; otherwise leave it 0 and
            # record the token amount, so nothing is silently mispriced
            fee_usd = fee if tokn in ("USDC", "USD") else D(0)
            upd.append((str(fee), tokn, str(fee_usd), rid))
            legs.add((inst, acct, prod, quote))
        print(f"[fees] to update: {len(upd):,} rows "
              f"({zero_fixed:,} zero-fee, {corrected:,} corrections)   "
              f"still-unfixable zero-fee CH rows: {unmatched:,} "
              f"(no S3 file for that day)")
        print(f"[fees] fee DELTA by token: "
              + ", ".join(f"{k} {v:+,.4f}" for k, v in sorted(by_token.items())))
        usd = sum(v for k, v in by_token.items() if k in ("USDC", "USD"))
        print(f"[fees] USD-denominated delta to book: ${usd:,.2f}")
        if dry:
            print("  (dry run — nothing written)")
            return
        from psycopg2.extras import execute_values
        with conn.cursor() as cur:
            for i in range(0, len(upd), 5000):
                execute_values(cur, """
                    UPDATE trades_spot_avgcost AS t
                       SET fee_amount = v.fee_amount,
                           fee_asset  = v.fee_asset,
                           fee_usd    = v.fee_usd
                      FROM (VALUES %s) AS v(fee_amount, fee_asset, fee_usd, id)
                     WHERE t.id = v.id
                """, upd[i:i + 5000],
                    template="(%s::numeric, %s::text, %s::numeric, %s::bigint)",
                    page_size=5000)
        conn.commit()
        print(f"[fees] updated {len(upd):,} rows across {len(legs)} legs")
        if "--no-refold" in sys.argv:
            print("  (--no-refold: realized P&L NOT recomputed)")
            return
        # a fee change moves realized P&L, so each touched leg must replay
        for inst in sorted({lg[0] for lg in legs}):
            try:
                n, tip = avgcost_db.refold_leg(conn, inst)
                print(f"  refold {inst:38} {n:>6} rows, tip qty {tip}")
            except Exception as e:
                print(f"  refold {inst:38} FAILED {type(e).__name__}: {e}")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
