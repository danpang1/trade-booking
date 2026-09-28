"""List the N most recent live transfer rows for Deal Enquiry.

Reads `{"limit": N}` from stdin (default 20, max 2000). Writes
{"ok": true, "rows": [...]}. Not portfolio-scoped: trades_transfer has
no portfolio column and the route is admin-only.
"""
from __future__ import annotations
import json
import sys

import transfer_db


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

    conn = transfer_db.connect()
    try:
        with conn.cursor() as cur:
            # Live row plus the earliest effective_start for the deal_ref,
            # so the UI can show the original booking moment.
            cur.execute(
                "SELECT t.*, "
                "       (SELECT MIN(effective_start) FROM trades_transfer "
                "         WHERE deal_ref = t.deal_ref) AS first_effective_start "
                "  FROM trades_transfer t "
                " WHERE t.effective_end IS NULL "
                " ORDER BY t.initiated_datetime DESC, t.deal_ref DESC "
                " LIMIT %s",
                (limit,),
            )
            cols = [d.name for d in cur.description]
            rows = [transfer_db.row_to_payload(cols, r) for r in cur.fetchall()]
        print(json.dumps({"ok": True, "rows": rows}))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
