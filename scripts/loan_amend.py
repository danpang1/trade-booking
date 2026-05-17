"""Amend an existing trades_loan row.

Atomic SCD2: UPDATE the current live row's effective_end (WHERE
effective_end IS NULL → row-locks so concurrent amends serialize),
then INSERT a new version. Cancel is amend with status='CANCELLED';
maturity is amend with status='MATURED'.

Reads JSON payload (single dict, deal_ref required) from stdin.
"""
from __future__ import annotations
import json
import sys

import loan_db


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2
    try:
        loan_db.validate_payload(payload, mode="amend")
    except loan_db.ValidationError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3
    deal_ref = payload["deal_ref"]
    cols, vals = loan_db.payload_to_columns(payload, deal_ref=deal_ref)

    conn = loan_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE trades_loan SET effective_end = NOW() "
                    "WHERE deal_ref = %s AND effective_end IS NULL "
                    "RETURNING deal_ref",
                    (deal_ref,),
                )
                if cur.fetchone() is None:
                    print(json.dumps({
                        "ok": False,
                        "error": f"{deal_ref} has no live row (already amended or never existed)",
                        "code": "conflict",
                    }))
                    return 4
                col_list = ", ".join(cols + ("effective_start", "effective_end"))
                placeholders = ", ".join(["%s"] * len(cols)) + ", NOW(), NULL"
                cur.execute(
                    f"INSERT INTO trades_loan ({col_list}) "
                    f"VALUES ({placeholders}) RETURNING *",
                    vals,
                )
                out_cols = [d.name for d in cur.description]
                row = loan_db.row_to_payload(out_cols, cur.fetchone())
        print(json.dumps({"ok": True, "rows": [row]}))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
