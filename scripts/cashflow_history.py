"""Return every row version for one deal_ref, ordered oldest → newest.

Used by the audit-trail UI in Deal Enquiry. Reads
`{"deal_ref": "MCF00000001"}` from stdin. Writes
`{"ok": true, "rows": [<v1>, <v2>, ...]}` on hit (rows in ascending
effective_start order so a UI can diff each row against its predecessor),
or `{"ok": false, "error": "...", "code": "not_found"}` if no rows
exist for the deal_ref (exit 4).
"""
from __future__ import annotations
import json
import sys

import cashflow_db
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

    conn = cashflow_db.connect()
    try:
        with conn.cursor() as cur:
            # Every version row gets the *current* mapping snapshot
            # attached — the map table isn't bitemporal so historical
            # mapping sets aren't recoverable. UI can still render
            # "currently linked to MLA…" alongside the SCD2 timeline.
            # LEFT JOIN bookings_draft on approved_deal_ref so the
            # audit-trail UI can display "approved by <human>" for the
            # initial booking when the trade came through the Claude
            # Code draft pipeline. trades_cashflow.user_id captures the
            # booker ("claude:<username>"), bookings_draft.approved_by
            # captures the human reviewer who clicked approve.
            cur.execute(
                f"SELECT t.*, {loan_cashflow_map_db.CASHFLOW_MAPPINGS_JSON_AGG}, "
                "       d.id          AS draft_id, "
                "       d.approved_by AS draft_approved_by, "
                "       d.approved_at AS draft_approved_at, "
                "       d.source      AS draft_source "
                "  FROM trades_cashflow t "
                "  LEFT JOIN loan_cashflow_map m ON m.cashflow_deal_ref = t.deal_ref "
                "  LEFT JOIN bookings_draft d ON d.approved_deal_ref = t.deal_ref "
                " WHERE t.deal_ref = %s "
                " GROUP BY t.deal_ref, t.effective_start, d.id "
                " ORDER BY t.effective_start ASC",
                (deal_ref,),
            )
            rows = cur.fetchall()
            if not rows:
                print(json.dumps({
                    "ok": False,
                    "error": f"no history for {deal_ref}",
                    "code": "not_found",
                }))
                return 4
            cols = [d.name for d in cur.description]
            out = [cashflow_db.row_to_payload(cols, r) for r in rows]
        print(json.dumps({"ok": True, "rows": out}))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
