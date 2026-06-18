"""Read the funding_settings key-value store.

Stdin JSON: {} (ignored — kept uniform with the other spawnPython scripts).

Stdout JSON:
  {"ok": true, "settings": {"capital": 6600000.0, "itd_pnl": 0.0}}
  {"ok": false, "error": "..."}   on DB error

Absent keys fall back to funding_settings_db.DEFAULTS, so a fresh DB still
returns a usable object.
"""
from __future__ import annotations
import json
import sys

import loan_db
import funding_settings_db


def main() -> int:
    conn = loan_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                settings = funding_settings_db.fetch_settings(cur)
        print(json.dumps({"ok": True, "settings": settings}))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
