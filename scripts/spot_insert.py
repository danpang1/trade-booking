"""Insert one new spot trade row.

Reads JSON payload from stdin. Writes JSON result to stdout:
  Success: {"ok": true, "rows": [<row JSON>], "attachments": [...]}
  Failure: {"ok": false, "error": "...", "detail": "..."}  (with non-zero exit)

Manual smoke (run against UAT):

    cat <<'EOF' | python3 trade-booking/scripts/spot_insert.py
    {
      "external_trade_id": "TEST-SMOKE-SPOT-001",
      "direction": "LONG",
      "entity": "TK006",
      "portfolio_id": 8006,
      "portfolio_name": "CDA",
      "counterparty": null,
      "counterparty_id": null,
      "account": "WALLET_CDA_EVM_04",
      "account_type": "WALLET",
      "base_asset": "BTC",
      "base_amount": "0.01",
      "quote_asset": "USDT",
      "quote_amount": "700",
      "price": "70000",
      "fee_asset": "USDT",
      "fee_amount": "0.35",
      "trade_date": "2026-05-19T12:00:00+00:00",
      "value_date": "2026-05-19T12:00:00+00:00",
      "txid_reference": null,
      "user_id": "smoke",
      "status": "PENDING",
      "comment": "smoke test — safe to delete"
    }
    EOF

After verification:
    psql ... -c "DELETE FROM trades_spot WHERE external_trade_id LIKE 'TEST-SMOKE-SPOT-%';"
"""
from __future__ import annotations
import json
import sys

import attachments_db
import spot_db


def main() -> int:
    raw = sys.stdin.read()
    try:
        _raw = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2
    # Accept either {payload: {...}, attachments: [...]} envelope or a bare
    # payload dict. The frontend sends the envelope shape via server.js.
    if isinstance(_raw, dict) and "payload" in _raw and isinstance(_raw["payload"], dict):
        payload = _raw["payload"]
        attachments = _raw.get("attachments") or []
    else:
        payload = _raw
        # Frontend stashes attachments under _meta when posting bare payload.
        meta = payload.get("_meta") if isinstance(payload, dict) else None
        attachments = (meta or {}).get("attachments") or []
    try:
        spot_db.validate_payload(payload, mode="insert")
    except spot_db.ValidationError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3

    conn = spot_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                # deal_ref assigned by the DB default
                # ('MFX' || lpad(nextval('trade_seq_spot'),8,'0')); omitted on
                # insert and read back from RETURNING *.
                cols, vals = spot_db.payload_to_columns(payload)
                col_list = ", ".join(cols + ("effective_start", "effective_end"))
                placeholders = ", ".join(["%s"] * len(cols)) + ", NOW(), NULL"
                cur.execute(
                    f"INSERT INTO trades_spot ({col_list}) VALUES ({placeholders}) RETURNING *",
                    vals,
                )
                out_cols = [d.name for d in cur.description]
                row = spot_db.row_to_payload(out_cols, cur.fetchone())

                inserted_atts = attachments_db.insert_attachments(
                    cur,
                    deal_ref=row["deal_ref"],
                    attachments=attachments,
                    user_id=payload.get("user_id") or "unknown",
                )
        print(json.dumps({"ok": True, "rows": [row], "attachments": inserted_atts}))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
