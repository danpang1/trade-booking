"""Approve a PENDING_REVIEW draft: claim it AND insert into the live
trade table inside a single BEGIN/COMMIT. If the live insert raises,
the whole txn rolls back — draft stays PENDING_REVIEW, no orphan row.

Stdin: {"id": 42, "_acting_user": "alice"}

Stdout success:  {"ok": true, "row": {...draft public...}, "deal_ref": "MCF000123"}
Stdout 404:      {"ok": false, "code": "not_found"}
Stdout 409:      {"ok": false, "code": "conflict", "error": "already approved or not pending"}
Stdout 400:      {"ok": false, "error": "<insert-time validation>"}
"""
from __future__ import annotations
import json
import sys

import draft_db
import draft_trade_link


def _approve(draft_id: int, acting: str) -> tuple[str, dict | None, str | None]:
    """Returns (status, draft_row, deal_ref). status in {'ok','not_found','conflict','bad_payload'}."""
    conn = draft_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                # Atomic claim: only PENDING_REVIEW rows owned by acting user.
                # SET also sets approved_at/by here so a race loses cleanly.
                cur.execute(
                    "UPDATE bookings_draft "
                    "   SET status = 'APPROVED', "
                    "       approved_at = now(), "
                    "       approved_by = %s "
                    " WHERE id = %s "
                    "   AND created_by = %s "
                    "   AND status = 'PENDING_REVIEW' "
                    "RETURNING id, category, payload, approved_deal_ref",
                    (acting, draft_id, acting),
                )
                claim = cur.fetchone()
                if claim is None:
                    # Either doesn't exist, or not owned, or not pending.
                    # Distinguish by re-selecting.
                    cur.execute(
                        "SELECT status FROM bookings_draft "
                        "WHERE id = %s AND created_by = %s",
                        (draft_id, acting),
                    )
                    found = cur.fetchone()
                    if found is None:
                        return "not_found", None, None
                    return "conflict", None, None

                _, category, payload, existing_ref = claim
                # Approving a draft is the human "yes, book it" gate, so
                # the booked row should be CONFIRMED, not PENDING. If the
                # user manually picked another status (CANCELLED, SETTLED,
                # etc.) we respect that as the manual override.
                #
                # The "claude:" prefix on user_id is KEPT, deliberately.
                # Approval used to strip it so a bot-booked trade read like a
                # form-booked one; that hid how the trade got there. A trade
                # booked through Colossus stays "claude:danny.pang" for life,
                # whoever approves it, so the blotter shows at a glance which
                # trades came in through the bot and who asked for them.
                if isinstance(payload, dict):
                    patched = dict(payload)
                    if patched.get("status") == "PENDING":
                        patched["status"] = "CONFIRMED"
                    payload = patched

                # The trade row already exists — draft_insert booked it as
                # PENDING. Approval MOVES it rather than creating it, on the
                # same cursor, so the claim above and the status change commit
                # together or not at all.
                deal_ref = (existing_ref or "").strip() or None
                if deal_ref is None:
                    raise draft_db.ValidationError(
                        f"draft {draft_id} has no trade row to approve "
                        f"(booked before the double-write flow — amend it "
                        f"directly in the blotter instead)"
                    )
                row = draft_trade_link.amend_status(
                    cur, category, deal_ref,
                    (payload or {}).get("status") or "CONFIRMED",
                    updated_by=acting,
                )

                cur.execute(
                    "UPDATE bookings_draft "
                    "   SET approved_deal_ref = %s "
                    " WHERE id = %s "
                    "RETURNING *",
                    (deal_ref, draft_id),
                )
                public = draft_db.row_to_public(cur, cur.fetchone())
                draft_trade_link.mirror_amend(category, row)
                return "ok", public, deal_ref
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
        status, row, deal_ref = _approve(draft_id, acting)
    except draft_db.ValidationError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3
    except Exception as e:
        # cashflow_insert errors (validation, DB constraint) land here.
        print(json.dumps({"ok": False, "error": "approve failed", "detail": str(e)}))
        return 3

    if status == "not_found":
        print(json.dumps({"ok": False, "code": "not_found", "error": "draft not found"}))
        return 4
    if status == "conflict":
        print(json.dumps({"ok": False, "code": "conflict",
                          "error": "already approved or not pending"}))
        return 7

    print(json.dumps({"ok": True, "row": row, "deal_ref": deal_ref}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
