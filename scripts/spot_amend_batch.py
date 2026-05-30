"""Bulk-amend spot trade rows in ONE transaction (all-or-nothing).

stdin JSON: {"rows": [<amend payload>, ...]}
Each payload is a full spot amend payload (same shape as spot_amend.py) plus an
optional "expected_effective_start" (ISO string) for optimistic concurrency: if
the live row's effective_start no longer matches, the whole batch aborts (the
row was changed by someone else since the client loaded it).

Writes JSON to stdout:
  Success:    {"ok": true, "rows": [...], "count": N}
  Conflict:   {"ok": false, "code": "conflict", "error": "...", "deal_ref": "..."}  (exit 4)
  Validation: {"ok": false, "error": "...", "deal_ref": "..."}                       (exit 3)

All-or-nothing: any failure rolls back every row — nothing is written.
"""
from __future__ import annotations
import json
import sys

import spot_db


class _BatchConflict(Exception):
    """A selected row is no longer the live version — abort the whole batch."""
    def __init__(self, deal_ref, msg):
        super().__init__(msg)
        self.deal_ref = deal_ref


def main() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2

    rows = data.get("rows") if isinstance(data, dict) else (data if isinstance(data, list) else None)
    if not isinstance(rows, list) or len(rows) == 0:
        print(json.dumps({"ok": False, "error": "expected a non-empty 'rows' array"}))
        return 3

    for i, p in enumerate(rows):
        if not isinstance(p, dict):
            print(json.dumps({"ok": False, "error": f"row {i} is not an object"}))
            return 3
        try:
            spot_db.validate_payload(p, mode="amend")
        except spot_db.ValidationError as e:
            print(json.dumps({"ok": False, "error": str(e), "deal_ref": p.get("deal_ref")}))
            return 3

    conn = spot_db.connect()
    out_rows = []
    try:
        with conn:
            with conn.cursor() as cur:
                for p in rows:
                    deal_ref = p["deal_ref"]
                    expected = p.get("expected_effective_start")
                    if expected:
                        cur.execute(
                            "UPDATE trades_spot SET effective_end = NOW() "
                            "WHERE deal_ref = %s AND effective_end IS NULL "
                            "AND effective_start = %s RETURNING deal_ref",
                            (deal_ref, expected),
                        )
                    else:
                        cur.execute(
                            "UPDATE trades_spot SET effective_end = NOW() "
                            "WHERE deal_ref = %s AND effective_end IS NULL "
                            "RETURNING deal_ref",
                            (deal_ref,),
                        )
                    if cur.fetchone() is None:
                        raise _BatchConflict(
                            deal_ref,
                            f"{deal_ref} is not the current live row (changed or removed "
                            f"since the page loaded) — batch aborted, nothing changed",
                        )

                    cols, vals = spot_db.payload_to_columns(p, deal_ref=deal_ref)
                    col_list = ", ".join(cols + ("effective_start", "effective_end"))
                    placeholders = ", ".join(["%s"] * len(cols)) + ", NOW(), NULL"
                    cur.execute(
                        f"INSERT INTO trades_spot ({col_list}) "
                        f"VALUES ({placeholders}) RETURNING *",
                        vals,
                    )
                    out_cols = [d.name for d in cur.description]
                    out_rows.append(spot_db.row_to_payload(out_cols, cur.fetchone()))
        print(json.dumps({"ok": True, "rows": out_rows, "count": len(out_rows)}))
        return 0
    except _BatchConflict as e:
        print(json.dumps({"ok": False, "code": "conflict", "error": str(e), "deal_ref": e.deal_ref}))
        return 4
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
