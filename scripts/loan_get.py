"""Fetch the single live (effective_end IS NULL) row for one loan deal_ref.

Reads `{"deal_ref": "MLA00000001"}` from stdin.
Writes {"ok": true, "rows": [<row>]} on hit, {"ok": false, ..., "code": "not_found"} on miss (exit 4).
"""
from __future__ import annotations
import json
import sys

import loan_db
import loan_cashflow_map_db


def main() -> int:
    raw = sys.stdin.read()
    try:
        params = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2
    deal_ref = (params.get("deal_ref") or "").strip()
    if not deal_ref:
        print(json.dumps({"ok": False, "error": "deal_ref is required"}))
        return 3

    conn = loan_db.connect()
    try:
        with conn.cursor() as cur:
            # Mappings include the linked cashflow's headline economics
            # (cf_type/direction/amount/asset) so the UI can show running
            # totals without a second round-trip. cf is the *live* cashflow
            # row only.
            cur.execute(
                f"SELECT t.*, {loan_cashflow_map_db.LOAN_MAPPINGS_JSON_AGG} "
                "  FROM trades_loan t "
                "  LEFT JOIN loan_cashflow_map m ON m.loan_deal_ref = t.deal_ref "
                "  LEFT JOIN trades_cashflow cf "
                "         ON cf.deal_ref = m.cashflow_deal_ref "
                "        AND cf.effective_end IS NULL AND cf.status <> 'CANCELLED' "
                " WHERE t.deal_ref = %s AND t.effective_end IS NULL "
                " GROUP BY t.deal_ref, t.effective_start",
                (deal_ref,),
            )
            row = cur.fetchone()
            if row is None:
                print(json.dumps({
                    "ok": False,
                    "error": f"no live row for {deal_ref}",
                    "code": "not_found",
                }))
                return 4
            cols = [d.name for d in cur.description]
            out = loan_db.row_to_payload(cols, row)
        print(json.dumps({"ok": True, "rows": [out]}))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
