"""Fetch the single live (effective_end IS NULL) spot row for one deal_ref.

Reads `{"deal_ref": "MFX00000001"}` from stdin.
Writes {"ok": true, "rows": [<row>]} on hit, {"ok": false, "error": "...", "code": "not_found"} on miss (exit 4).
"""
from __future__ import annotations
import json
import sys

import spot_db


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

    conn = spot_db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM trades_spot "
                " WHERE deal_ref = %s AND effective_end IS NULL",
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
            out = spot_db.row_to_payload(cols, row)
        print(json.dumps({"ok": True, "rows": [out]}))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
