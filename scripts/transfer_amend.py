"""Amend a transfer (SCD2: close the live row, insert a new version).

Cancel is an amend with status='CANCELLED'. After the MO commit the new
version is mirrored into the tech DB's manual_transfer (best-effort). Reads a single-dict payload
(deal_ref required) from stdin. Writes:
  Success:  {"ok": true, "rows": [<row>], "attachments": [...]}
  Conflict: {"ok": false, "error": "...", "code": "conflict"}   (exit 4)
  Invalid:  {"ok": false, "error": "..."}                       (exit 3)
"""
from __future__ import annotations
import json
import sys

import attachments_db
import transfer_db
import authorship


def _dual_write_manual_transfer_amend(row: dict) -> None:
    """Best-effort manual_transfer mirror for any amend (incl. cancel): closes
    the prior open version and inserts the new one (SCD2), after the MO
    commit. Never affects the amend -- all errors (incl. import) swallowed."""
    try:
        import manual_write

        manual_write.write_manual_transfer_amend(row)
    except Exception as e:  # noqa: BLE001
        print(f"manual dual-write: skip manual_transfer amend: {e!r}", file=sys.stderr)


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
        transfer_db.validate_payload(payload, mode="amend")
    except transfer_db.ValidationError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3

    # Re-resolve an own-side id only where it is blank, so a corrected
    # account gets its id and a hand-corrected id is kept.
    transfer_db.stamp_account_ids(payload)

    deal_ref = payload["deal_ref"]
    conn = transfer_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE transfer SET effective_end = NOW() "
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
                # Created By stays the original booker; the amender goes
                # to updated_by.
                authorship.apply_on_amend(cur, "transfer", payload, deal_ref)
                cols, vals = transfer_db.payload_to_columns(payload, deal_ref=deal_ref)
                col_list = ", ".join(cols + ("effective_start", "effective_end"))
                placeholders = ", ".join(["%s"] * len(cols)) + ", NOW(), NULL"
                cur.execute(
                    f"INSERT INTO transfer ({col_list}) "
                    f"VALUES ({placeholders}) RETURNING *",
                    vals,
                )
                out_cols = [d.name for d in cur.description]
                row = transfer_db.row_to_payload(out_cols, cur.fetchone())
                inserted_atts = attachments_db.insert_attachments(
                    cur,
                    deal_ref=deal_ref,
                    attachments=attachments,
                    user_id=payload.get("user_id") or "unknown",
                )
        print(json.dumps({"ok": True, "rows": [row], "attachments": inserted_atts}))
        _dual_write_manual_transfer_amend(row)
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
