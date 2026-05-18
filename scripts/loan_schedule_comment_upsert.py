"""Upsert one schedule comment for a loan.

Stdin JSON:
  {
    "deal_ref":                  "MLA00000008",
    "trigger_cashflow_deal_ref": "MCF00000011",
    "period_start_date":         "2025-02-14",   # informational; refreshed
    "comment":                   "free text or empty to clear",
    "user_id":                   "danny.pang"
  }

Stdout JSON:
  {"ok": true, "row": {...}}      on success
  {"ok": false, "error": "..."}   on validation or DB error
"""
from __future__ import annotations
import json
import sys

import loan_db
import loan_schedule_comments_db


def main() -> int:
    raw = sys.stdin.read()
    try:
        params = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2

    deal_ref = (params.get("deal_ref") or "").strip()
    trigger_ref = (params.get("trigger_cashflow_deal_ref") or "").strip()
    psd = params.get("period_start_date")
    comment = params.get("comment")
    user_id = (params.get("user_id") or "").strip()

    if not deal_ref:
        print(json.dumps({"ok": False, "error": "deal_ref is required"}))
        return 3
    if not trigger_ref:
        print(json.dumps({"ok": False, "error": "trigger_cashflow_deal_ref is required"}))
        return 3
    if not psd:
        print(json.dumps({"ok": False, "error": "period_start_date is required"}))
        return 3
    if not user_id:
        print(json.dumps({"ok": False, "error": "user_id is required"}))
        return 3

    conn = loan_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                row = loan_schedule_comments_db.upsert_comment(
                    cur,
                    loan_deal_ref=deal_ref,
                    trigger_cashflow_deal_ref=trigger_ref,
                    period_start_date=psd,
                    comment=comment,
                    user_id=user_id,
                )
        print(json.dumps({"ok": True, "row": row}))
        return 0
    except loan_schedule_comments_db.ScheduleCommentError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
