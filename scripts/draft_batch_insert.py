"""Insert N bookings_draft rows for the acting user, atomically.

Stdin:
  {"trades": [
     {"category": "CASHFLOW", "payload": {...}, "client_request_id": "<uuid>"},
     ...
   ],
   "_acting_user": "alice"}

Stdout success: {"ok": true, "batch_id": "<uuid>", "created": N, "rows": [...]}
Stdout failure: {"ok": false, "error": "..."}

If any single trade fails validation, the WHOLE batch rolls back
(no rows inserted). Dedupe is per-trade: if a client_request_id
already exists, that row is returned unchanged AND counted in 'created'
under its existing batch_id (a new batch_id is only allocated for
genuinely new rows in this call).
"""
from __future__ import annotations
import json
import sys
import uuid

import draft_db


def _insert_batch(body: dict) -> dict:
    acting = body.get("_acting_user")
    if not isinstance(acting, str) or not acting:
        raise draft_db.ValidationError("missing _acting_user (server bug)")
    trades = body.get("trades")
    if not isinstance(trades, list) or not trades:
        raise draft_db.ValidationError("'trades' must be a non-empty list")
    if len(trades) > 50:
        raise draft_db.ValidationError("batch too large (max 50 trades)")

    # Pre-validate everything BEFORE opening a txn so all errors surface
    # without holding locks. The DB UNIQUE constraint on client_request_id
    # backs this up at write time.
    prepared = []
    seen_crids = set()
    for i, t in enumerate(trades):
        if not isinstance(t, dict):
            raise draft_db.ValidationError(f"trade {i}: not an object")
        cat = draft_db.validate_category(t.get("category"))
        crid = draft_db.validate_uuid(t.get("client_request_id"))
        if crid in seen_crids:
            raise draft_db.ValidationError(
                f"trade {i}: duplicate client_request_id within batch: {crid}"
            )
        seen_crids.add(crid)
        payload = t.get("payload")
        # Stamp user_id, then shape-validate
        if isinstance(payload, dict):
            payload = {**payload, "user_id": acting}
        draft_db.validate_payload_for_category(cat, payload)
        prepared.append((cat, payload, crid))

    batch_id = str(uuid.uuid4())
    out_rows = []
    conn = draft_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                for cat, payload, crid in prepared:
                    cur.execute(
                        "SELECT * FROM bookings_draft WHERE client_request_id = %s",
                        (crid,),
                    )
                    existing = cur.fetchone()
                    if existing is not None:
                        out_rows.append(draft_db.row_to_public(cur, existing))
                        continue
                    cur.execute(
                        "INSERT INTO bookings_draft "
                        "(category, payload, source, status, batch_id, "
                        " client_request_id, created_by) "
                        "VALUES (%s, %s, 'CLAUDE_CODE', 'PENDING_REVIEW', "
                        "        %s, %s, %s) "
                        "RETURNING *",
                        (cat, json.dumps(payload), batch_id, crid, acting),
                    )
                    out_rows.append(draft_db.row_to_public(cur, cur.fetchone()))
    finally:
        conn.close()

    return {
        "ok": True,
        "batch_id": batch_id,
        "created": len(out_rows),
        "rows": out_rows,
    }


def main() -> int:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig").strip() or "{}"
        body = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2

    try:
        result = _insert_batch(body)
    except draft_db.ValidationError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
