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
            cur.execute(
                "SELECT * FROM trades_cashflow "
                "WHERE deal_ref = %s "
                "ORDER BY effective_start ASC",
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
