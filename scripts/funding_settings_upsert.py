"""Upsert one funding setting (capital, itd_pnl or illiquid_assets).

Stdin JSON:
  {"key": "capital", "value": 6600000, "user_id": "danny.pang"}

Stdout JSON:
  {"ok": true, "row": {...}}      on success
  {"ok": false, "error": "..."}   on validation or DB error
"""
from __future__ import annotations
import json
import sys

import loan_db
import funding_settings_db


def main() -> int:
    raw = sys.stdin.read()
    try:
        params = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2

    key = (params.get("key") or "").strip()
    value = params.get("value")
    user_id = (params.get("user_id") or "").strip()

    if not key:
        print(json.dumps({"ok": False, "error": "key is required"}))
        return 3
    if value is None:
        print(json.dumps({"ok": False, "error": "value is required"}))
        return 3
    if not user_id:
        print(json.dumps({"ok": False, "error": "user_id is required"}))
        return 3

    conn = loan_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                row = funding_settings_db.upsert_setting(
                    cur,
                    key=key,
                    value=value,
                    user_id=user_id,
                )
        print(json.dumps({"ok": True, "row": row}))
        return 0
    except funding_settings_db.FundingSettingError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
