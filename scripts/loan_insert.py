"""Insert one trades_loan row.

Reads JSON payload from stdin. Writes JSON result to stdout:
  Success: {"ok": true, "rows": [<row JSON>]}
  Failure: {"ok": false, "error": "...", "detail": "..."}  (non-zero exit)

Manual smoke (run against UAT):

    cd /Users/weiyiao/Projects/nxgen-mo-tools
    cat <<'EOF' | python3 trade-booking/scripts/loan_insert.py
    {
      "order_id": "TEST-SMOKE-INS-LOAN-001",
      "direction": "BORROW",
      "loan_type": "VIP LOAN",
      "entity": "TK006",
      "portfolio_id": 8006,
      "portfolio_name": "CDA",
      "counterparty": "Binance",
      "account": "EXCHANGE_CDA_BINANCE",
      "account_type": "EXCHANGE",
      "principal_asset": "USDT",
      "principal_amount": "100",
      "interest_asset": "USDT",
      "interest_rate_pa_pct": "5.25",
      "interest_type": "FIXED",
      "floating_benchmark": null,
      "collateral_asset": null,
      "collateral_amount": null,
      "is_hedged": false,
      "trade_date": "2026-05-15T12:00:00+00:00",
      "maturity_date": "2026-06-14T12:00:00+00:00",
      "user_id": "smoke",
      "status": "LIVE",
      "comment": "smoke test — safe to delete"
    }
    EOF

After verification:
    psql ... -c "DELETE FROM trades_loan WHERE order_id LIKE 'TEST-SMOKE-INS-LOAN-%';"
"""
from __future__ import annotations
import json
import sys

import attachments_db
import loan_db


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
        loan_db.validate_payload(payload, mode="insert")
    except loan_db.ValidationError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3

    conn = loan_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT nextval('trade_seq_loan')")
                n = cur.fetchone()[0]
                # Format: MLA + 8-digit zero-padded (Manual LoAn).
                deal_ref = f"MLA{n:08d}"
                cols, vals = loan_db.payload_to_columns(payload, deal_ref=deal_ref)
                col_list = ", ".join(cols + ("effective_start", "effective_end"))
                placeholders = ", ".join(["%s"] * len(cols)) + ", NOW(), NULL"
                cur.execute(
                    f"INSERT INTO trades_loan ({col_list}) VALUES ({placeholders}) RETURNING *",
                    vals,
                )
                out_cols = [d.name for d in cur.description]
                row = loan_db.row_to_payload(out_cols, cur.fetchone())
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
