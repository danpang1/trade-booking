"""Insert one or two (mirror-leg) cashflow rows.

Reads JSON payload from stdin. Writes JSON result to stdout:
  Success: {"ok": true, "rows": [<row JSON>, ...]}
  Failure: {"ok": false, "error": "...", "detail": "..."}  (with non-zero exit)

Manual smoke (run against UAT):

    cd /Users/weiyiao/Projects/nxgen-mo-tools
    cat <<'EOF' | python3 trade-booking/scripts/cashflow_insert.py
    {
      "external_trade_id": "TEST-SMOKE-INS-001",
      "cashflow_type": "FUNDING IN",
      "direction": "INCOMING",
      "entity": "TK006",
      "portfolio_id": 8006,
      "portfolio_name": "CDA",
      "counterparty": "Galaxy",
      "account": "WALLET_CDA_EVM_04",
      "account_type": "WALLET",
      "asset": "USDC",
      "amount": "1.00",
      "fee_asset": null,
      "fee_amount": "0",
      "trade_date": "2026-05-15T12:00:00+00:00",
      "value_date": "2026-05-15T12:00:00+00:00",
      "network": "BSC",
      "txid_reference": null,
      "user_id": "smoke",
      "status": "PENDING",
      "comment": "smoke test — safe to delete"
    }
    EOF

After verification:
    psql ... -c "DELETE FROM trades_cashflow WHERE external_trade_id LIKE 'TEST-SMOKE-INS-%';"
"""
from __future__ import annotations
import json
import sys

import attachments_db
import cashflow_db
import loan_cashflow_map_db


def _insert_one(cur, payload: dict) -> dict:
    # deal_ref is assigned by the table's DB default
    # ('MCF' || lpad(nextval('trade_seq_cashflow'),8,'0')) — we omit it on
    # insert (payload_to_columns drops the column when deal_ref is None) and
    # read the generated value back from RETURNING *.
    cols, vals = cashflow_db.payload_to_columns(payload)
    # Build INSERT: data columns + effective_start (NOW()) + effective_end (NULL)
    col_list = ", ".join(cols + ("effective_start", "effective_end"))
    placeholders = ", ".join(["%s"] * len(cols)) + ", NOW(), NULL"
    cur.execute(
        f"INSERT INTO trades_cashflow ({col_list}) VALUES ({placeholders}) RETURNING *",
        vals,
    )
    out_cols = [d.name for d in cur.description]
    row = cashflow_db.row_to_payload(out_cols, cur.fetchone())
    deal_ref = row["deal_ref"]  # DB-generated

    # Loan mappings (optional). The frontend stashes them in _meta so
    # they don't pollute the column-aligned cashflow payload. Mapping
    # write rides on the same txn — atomic with the cashflow insert.
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
    return row


def main() -> int:
    raw = sys.stdin.read()
    try:
        _raw = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2
    if isinstance(_raw, dict) and "payload" in _raw and isinstance(_raw["payload"], dict):
        payload = _raw["payload"]
        attachments = _raw.get("attachments") or []
    else:
        payload = _raw
        attachments = []
    try:
        cashflow_db.validate_payload(payload, mode="insert")
    except cashflow_db.ValidationError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3
    legs = payload if isinstance(payload, list) else [payload]
    conn = cashflow_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                rows = [_insert_one(cur, leg) for leg in legs]
                # Attachments attach only to leg 1's deal_ref; leg 2 (mirror) gets none.
                inserted_atts = attachments_db.insert_attachments(
                    cur,
                    deal_ref=rows[0]["deal_ref"],
                    attachments=attachments,
                    user_id=legs[0].get("user_id") or "unknown",
                )
        print(json.dumps({"ok": True, "rows": rows, "attachments": inserted_atts}))
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
