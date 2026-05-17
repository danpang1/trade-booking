"""Amend an existing cashflow row.

Atomic SCD2: UPDATE the current live row's effective_end (single
WHERE effective_end IS NULL → row-locks so concurrent amends serialize),
then INSERT a new version with the amended fields. Cancel is just amend
with status='CANCELLED'.

Reads JSON payload (single dict, deal_ref required) from stdin. Writes
JSON result to stdout:
  Success: {"ok": true, "rows": [<row JSON>]}
  Conflict (no live row): {"ok": false, "error": "<msg>", "code": "conflict"}  (exit 4)
  Validation: {"ok": false, "error": "..."} (exit 3)

Manual smoke (run against UAT after running cashflow_insert.py smoke first
and recording its deal_ref):

    DEAL=MCF-123  # replace with the deal_ref printed by insert smoke
    cat <<EOF | python3 trade-booking/scripts/cashflow_amend.py
    {
      "deal_ref": "$DEAL",
      "external_trade_id": "TEST-SMOKE-AMD-001",
      "cashflow_type": "FUNDING IN",
      "direction": "INCOMING",
      "entity": "TK006",
      "portfolio_id": 8006,
      "portfolio_name": "CDA",
      "counterparty": "Galaxy",
      "account": "WALLET_CDA_EVM_04",
      "account_type": "WALLET",
      "asset": "USDC",
      "amount": "2.00",
      "fee_asset": null, "fee_amount": "0",
      "trade_date": "2026-05-15T12:00:00+00:00",
      "value_date": "2026-05-15T12:00:00+00:00",
      "network": "BSC", "txid_reference": null,
      "user_id": "smoke", "status": "CONFIRMED",
      "comment": "amend smoke"
    }
    EOF

Verify in psql:
    SELECT deal_ref, amount, status, effective_start, effective_end
      FROM trades_cashflow WHERE deal_ref='MCF-123' ORDER BY effective_start;
Expected: 2 rows. First has effective_end stamped; second has effective_end NULL and amount=2.00.
"""
from __future__ import annotations
import json
import sys

import cashflow_db
import loan_cashflow_map_db


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2
    try:
        cashflow_db.validate_payload(payload, mode="amend")
    except cashflow_db.ValidationError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3
    if isinstance(payload, list):
        print(json.dumps({"ok": False, "error": "amend takes a single record, not a list"}))
        return 3
    deal_ref = payload["deal_ref"]
    cols, vals = cashflow_db.payload_to_columns(payload, deal_ref=deal_ref)

    conn = cashflow_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                # Atomically close the live row.
                cur.execute(
                    "UPDATE trades_cashflow SET effective_end = NOW() "
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
                # Insert the new version. deal_ref preserved; new effective window.
                col_list = ", ".join(cols + ("effective_start", "effective_end"))
                placeholders = ", ".join(["%s"] * len(cols)) + ", NOW(), NULL"
                cur.execute(
                    f"INSERT INTO trades_cashflow ({col_list}) "
                    f"VALUES ({placeholders}) RETURNING *",
                    vals,
                )
                out_cols = [d.name for d in cur.description]
                row = cashflow_db.row_to_payload(out_cols, cur.fetchone())

                # Mapping replace runs in the same txn as the SCD2
                # rewrite; if it fails (bad MLA ref) the whole amend
                # rolls back including the new cashflow version.
                meta = payload.get("_meta") or {}
                refs = meta.get("loan_deal_refs") or []
                mappings = loan_cashflow_map_db.set_mappings_for_cashflow(
                    cur,
                    cashflow_deal_ref=deal_ref,
                    loan_deal_refs=refs,
                    user_id=payload.get("user_id") or "unknown",
                    cashflow_type=payload.get("cashflow_type"),
                    direction=payload.get("direction"),
                )
                row["mappings"] = [
                    {
                        "counterpart_deal_ref": m["loan_deal_ref"],
                        "mapping_type": m["mapping_type"],
                        "mapped_amount": m["mapped_amount"],
                    }
                    for m in mappings
                ]
        print(json.dumps({"ok": True, "rows": [row]}))
        return 0
    except loan_cashflow_map_db.MappingError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
