"""List N most recent live loan rows for Deal Enquiry.

Reads `{"limit": N}` from stdin (default 20, max 200).
Writes {"ok": true, "rows": [...]} to stdout.
"""
from __future__ import annotations
import json
import sys

import loan_db
import loan_cashflow_map_db
import loan_schedule_comments_db


def main() -> int:
    raw = sys.stdin.read().strip() or "{}"
    try:
        params = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2
    try:
        limit = int(params.get("limit", 20))
    except (TypeError, ValueError):
        print(json.dumps({"ok": False, "error": "limit must be integer"}))
        return 3
    limit = max(1, min(200, limit))

    conn = loan_db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT t.*, "
                "       (SELECT MIN(effective_start) FROM trades_loan "
                "         WHERE deal_ref = t.deal_ref) AS first_effective_start, "
                f"      {loan_cashflow_map_db.LOAN_MAPPINGS_JSON_AGG}, "
                f"      {loan_schedule_comments_db.LOAN_SCHEDULE_COMMENTS_JSON_AGG} "
                "  FROM trades_loan t "
                "  LEFT JOIN loan_cashflow_map m ON m.loan_deal_ref = t.deal_ref "
                "  LEFT JOIN trades_cashflow cf "
                "         ON cf.deal_ref = m.cashflow_deal_ref "
                "        AND cf.effective_end IS NULL AND cf.status <> 'CANCELLED' "
                " WHERE t.effective_end IS NULL "
                " GROUP BY t.deal_ref, t.effective_start "
                " ORDER BY t.trade_date DESC, t.deal_ref DESC "
                " LIMIT %s",
                (limit,),
            )
            cols = [d.name for d in cur.description]
            rows = [loan_db.row_to_payload(cols, r) for r in cur.fetchall()]
        print(json.dumps({"ok": True, "rows": rows}))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
