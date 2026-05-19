"""GET handler script: read {"deal_ref": "..."} on stdin, print attachments.

Reads stdin JSON, looks up live ('uploaded') attachments for the deal_ref
via attachments_db.get_attachments_for_deal_ref, and prints the result.

Output (success):
  {"ok": true, "attachments": [<row JSON>, ...]}
Output (failure):
  {"ok": false, "error": "...", "detail": "..."}  (with non-zero exit)

Manual smoke:
    echo '{"deal_ref":"MCF00000042"}' | python3 trade-booking/scripts/attachments_get.py
"""
from __future__ import annotations
import json
import sys

import cashflow_db        # reuse the existing creds + connect helper
import attachments_db


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2

    if not isinstance(payload, dict):
        print(json.dumps({"ok": False, "error": "stdin must be a JSON object"}))
        return 3

    deal_ref = (payload.get("deal_ref") or "").strip()
    if not deal_ref:
        print(json.dumps({"ok": False, "error": "deal_ref required"}))
        return 3

    conn = cashflow_db.connect()
    try:
        with conn.cursor() as cur:
            rows = attachments_db.get_attachments_for_deal_ref(cur, deal_ref=deal_ref)
        print(json.dumps({"ok": True, "attachments": rows}))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
