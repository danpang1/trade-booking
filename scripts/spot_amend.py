"""Amend an existing spot trade row.

Atomic SCD2: UPDATE the current live row's effective_end (single
WHERE effective_end IS NULL → row-locks so concurrent amends serialize),
then INSERT a new version with the amended fields. Cancel is just amend
with status='CANCELLED'.

Reads JSON payload (single dict, deal_ref required) from stdin. Writes:
  Success: {"ok": true, "rows": [<row JSON>], "attachments": [...]}
  Conflict (no live row): {"ok": false, "error": "<msg>", "code": "conflict"}  (exit 4)
  Validation: {"ok": false, "error": "..."} (exit 3)

Manual smoke (run against UAT after running spot_insert.py first
and recording its deal_ref):

    DEAL=MFX00000001  # replace with the deal_ref printed by insert smoke
    cat <<EOF | python3 trade-booking/scripts/spot_amend.py
    {
      "deal_ref": "$DEAL",
      "external_trade_id": "TEST-SMOKE-SPOT-AMD-001",
      "direction": "LONG",
      "entity": "TK006",
      "portfolio_id": 8006,
      "portfolio_name": "CDA",
      "counterparty": null,
      "counterparty_id": null,
      "account": "WALLET_CDA_EVM_04",
      "account_type": "WALLET",
      "base_asset": "BTC", "base_amount": "0.02",
      "quote_asset": "USDT", "quote_amount": "1400",
      "price": "70000",
      "fee_asset": "USDT", "fee_amount": "0.7",
      "trade_date": "2026-05-19T12:00:00+00:00",
      "value_date": "2026-05-19T12:00:00+00:00",
      "txid_reference": null,
      "user_id": "smoke", "status": "CONFIRMED",
      "comment": "amend smoke"
    }
    EOF

Verify in psql:
    SELECT deal_ref, base_amount, status, effective_start, effective_end
      FROM trades_spot WHERE deal_ref='MFX00000001' ORDER BY effective_start;
Expected: 2 rows. First has effective_end stamped; second has effective_end NULL and base_amount=0.02.
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
    if isinstance(_raw, dict) and "payload" in _raw and isinstance(_raw["payload"], dict):
        payload = _raw["payload"]
        attachments = _raw.get("attachments") or []
    else:
        payload = _raw
        meta = payload.get("_meta") if isinstance(payload, dict) else None
        attachments = (meta or {}).get("attachments") or []
    try:
        spot_db.validate_payload(payload, mode="amend")
    except spot_db.ValidationError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3
    deal_ref = payload["deal_ref"]
    cols, vals = spot_db.payload_to_columns(payload, deal_ref=deal_ref)

    conn = spot_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                # Atomically close the live row.
                cur.execute(
                    "UPDATE trades_spot SET effective_end = NOW() "
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
                    f"INSERT INTO trades_spot ({col_list}) "
                    f"VALUES ({placeholders}) RETURNING *",
                    vals,
                )
                out_cols = [d.name for d in cur.description]
                row = spot_db.row_to_payload(out_cols, cur.fetchone())

                inserted_atts = attachments_db.insert_attachments(
                    cur,
                    deal_ref=deal_ref,
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
