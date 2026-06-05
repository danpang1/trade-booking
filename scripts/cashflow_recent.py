"""List the N most recent live cashflow rows for the Deal Enquiry view.

Reads `{"limit": N}` from stdin (default 20, max 2000).
Writes {"ok": true, "rows": [...]} to stdout.

Manual smoke:
    echo '{"limit": 5}' | python3 trade-booking/scripts/cashflow_recent.py
"""
from __future__ import annotations
import json
import sys

import cashflow_db
import loan_cashflow_map_db


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
    limit = max(1, min(2000, limit))

    conn = cashflow_db.connect()
    try:
        with conn.cursor() as cur:
            # Pull the live row plus the *earliest* effective_start for
            # the same deal_ref so the UI can show "Input Date" as the
            # original booking moment (immutable across amendments).
            # LEFT JOIN attaches mapped loan refs as a JSON array.
            cur.execute(
                "SELECT t.*, "
                "       (SELECT MIN(effective_start) FROM trades_cashflow "
                "         WHERE deal_ref = t.deal_ref) AS first_effective_start, "
                f"      {loan_cashflow_map_db.CASHFLOW_MAPPINGS_JSON_AGG} "
                "  FROM trades_cashflow t "
                "  LEFT JOIN loan_cashflow_map m ON m.cashflow_deal_ref = t.deal_ref "
                " WHERE t.effective_end IS NULL "
                " GROUP BY t.id "
                " ORDER BY t.trade_date DESC, t.deal_ref DESC "
                " LIMIT %s",
                (limit,),
            )
            cols = [d.name for d in cur.description]
            rows = [cashflow_db.row_to_payload(cols, r) for r in cur.fetchall()]
        print(json.dumps({"ok": True, "rows": rows}))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
