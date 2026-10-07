"""Reject a PENDING_REVIEW draft (soft: sets rejected_at). Owner only.

Stdin: {"id": 42, "reason": "optional text", "_acting_user": "alice"}

Stdout success: {"ok": true, "row": {...}, "sibling_draft_id": 43 | null}
  sibling_draft_id names the twin draft of an INTERNAL transfer pair that
  this rejection retired as well (see draft_trade_link.move_sibling_draft).
Stdout 404:     {"ok": false, "code": "not_found"}
Stdout 409:     {"ok": false, "code": "conflict"}
"""
from __future__ import annotations
import json
import sys

import draft_db
import draft_trade_link


def _reject(draft_id: int, reason, acting: str) -> tuple[str, dict | None, int | None]:
    if reason is not None and not isinstance(reason, str):
        raise draft_db.ValidationError("reason must be a string or null")
    conn = draft_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE bookings_draft "
                    "   SET status = 'REJECTED', "
                    "       rejected_at = now(), "
                    "       rejected_by = %s, "
                    "       rejection_reason = %s "
                    " WHERE id = %s "
                    "   AND created_by = %s "
                    "   AND status = 'PENDING_REVIEW' "
                    "RETURNING *",
                    (acting, reason, draft_id, acting),
                )
                row = cur.fetchone()
                if row is None:
                    # Distinguish not_found vs conflict
                    cur.execute(
                        "SELECT 1 FROM bookings_draft WHERE id = %s AND created_by = %s",
                        (draft_id, acting),
                    )
                    if cur.fetchone() is None:
                        return "not_found", None, None
                    return "conflict", None, None

                # The trade row was booked as PENDING when the draft was
                # created, so a rejection has to retire it too — otherwise a
                # refused booking stays live in the book. Cancelled, not
                # deleted: trades_* are bitemporal, and "someone booked this
                # and it was refused" is worth keeping.
                public = draft_db.row_to_public(cur, row)
                deal_ref = (public.get("approved_deal_ref") or "").strip()
                sibling_draft = None
                if deal_ref:
                    moved = draft_trade_link.amend_status(
                        cur, public.get("category"), deal_ref, "CANCELLED",
                        updated_by=acting,
                    )
                    draft_trade_link.mirror_amend(public.get("category"), moved)
                    # An INTERNAL transfer is a pair: retire the mirror too.
                    for sib in draft_trade_link.sibling_refs(
                            public.get("category"), public.get("payload")):
                        m2 = draft_trade_link.amend_status(
                            cur, public.get("category"), sib, "CANCELLED",
                            updated_by=acting,
                        )
                        draft_trade_link.mirror_amend(public.get("category"), m2)
                    # ...and the mirror leg's own draft card.
                    sibling_draft = draft_trade_link.move_sibling_draft(
                        cur, public.get("payload"), "REJECTED", acting, reason,
                    )
                return "ok", public, sibling_draft
    finally:
        conn.close()


def main() -> int:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig").strip() or "{}"
        body = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2

    draft_id = body.get("id")
    acting = body.get("_acting_user")
    if not isinstance(draft_id, int) or draft_id <= 0:
        print(json.dumps({"ok": False, "error": "id must be positive integer"}))
        return 3
    if not isinstance(acting, str) or not acting:
        print(json.dumps({"ok": False, "error": "missing _acting_user (server bug)"}))
        return 3

    try:
        status, row, sibling_draft = _reject(draft_id, body.get("reason"), acting)
    except draft_db.ValidationError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5

    if status == "not_found":
        print(json.dumps({"ok": False, "code": "not_found", "error": "draft not found"}))
        return 4
    if status == "conflict":
        print(json.dumps({"ok": False, "code": "conflict", "error": "draft is not PENDING_REVIEW"}))
        return 7

    print(json.dumps({"ok": True, "row": row, "sibling_draft_id": sibling_draft}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
