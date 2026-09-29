"""Book a transfer: one row with both ends on it -- or, for an INTERNAL
transfer, the pair: the leg as booked plus its mirror on the other
account (transfer_db.mirror_leg), inserted in one transaction.

Reads JSON from stdin -- a bare payload dict or the {payload, attachments}
envelope server.js sends. Writes to stdout:
  Success: {"ok": true, "rows": [<row>], "attachments": [...]}
  Failure: {"ok": false, "error": "...", "detail": "..."}  (non-zero exit)

There is no tech-DB mirror yet. manual_trade / manual_cashflow feed the
position service and a transfer is neither; until a manual_transfer table
exists on that side, transfers live in the MO book only, and this is
logged on every insert so it is not forgotten.
"""
from __future__ import annotations
import json
import sys

import attachments_db
import transfer_db


def _insert_one(cur, payload: dict) -> dict:
    """Insert one transfer row on the given cursor and return the live row.

    deal_ref comes from the table default ('MTR' || nextval), read back
    from RETURNING *. Reusable inside another transaction.
    """
    cols, vals = transfer_db.payload_to_columns(payload)
    col_list = ", ".join(cols + ("effective_start", "effective_end"))
    placeholders = ", ".join(["%s"] * len(cols)) + ", NOW(), NULL"
    cur.execute(
        f"INSERT INTO transfer ({col_list}) VALUES ({placeholders}) RETURNING *",
        vals,
    )
    out_cols = [d.name for d in cur.description]
    return transfer_db.row_to_payload(out_cols, cur.fetchone())


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
        meta = _raw.get("_meta") or payload.get("_meta") or {}
    else:
        payload = _raw
        meta = (payload.get("_meta") if isinstance(payload, dict) else None) or {}
        attachments = meta.get("attachments") or []
    # The mirror leg is on by default; the form's "Mirror leg" box (like
    # the INTER PTF FUNDING "Mirror Trade" one) turns it off when the
    # other side is booked separately or not at all.
    want_mirror = meta.get("mirror", True) is not False
    try:
        transfer_db.validate_payload(payload, mode="insert")
    except transfer_db.ValidationError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3

    # Gateway ids for our end(s), recorded with the row rather than
    # re-derived later; the counterparty end stays as typed.
    transfer_db.stamp_account_ids(payload)
    legs = [payload]
    if payload.get("transfer_type") == "INTERNAL" and want_mirror:
        legs.append(transfer_db.mirror_leg(payload))

    conn = transfer_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                rows = [_insert_one(cur, leg) for leg in legs]
                # Attachments hang off the leg as booked; the mirror gets none.
                inserted_atts = attachments_db.insert_attachments(
                    cur,
                    deal_ref=rows[0]["deal_ref"],
                    attachments=attachments,
                    user_id=payload.get("user_id") or "unknown",
                )
        print(json.dumps({"ok": True, "rows": rows, "attachments": inserted_atts}))
        print(
            "manual dual-write: no manual_transfer table in the tech DB yet - "
            f"{', '.join(r['deal_ref'] for r in rows)} recorded in the MO book only",
            file=sys.stderr,
        )
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
