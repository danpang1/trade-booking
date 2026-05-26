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
from cashflow_insert import _insert_one as cashflow_insert_one


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
                    "RETURNING id, category, payload",
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

                _, category, payload = claim
                if category != "CASHFLOW":
                    # Plan 1a is CASHFLOW-only. SPOT drafts can be created
                    # at the DB level (CHECK allows it) but approving one
                    # would require spot_insert._insert_one, wired in Phase 2.
                    raise draft_db.ValidationError(
                        f"approve not implemented for category {category}"
                    )

                # IN-PROCESS insert into trades_cashflow on the SAME cursor.
                # The booker prefix ("claude:<username>") was stamped onto
                # payload.user_id at draft creation (draft_insert.py /
                # draft_batch_insert.py), so this path passes it through
                # unchanged. The human approver is preserved separately on
                # bookings_draft.approved_by.
                # If this raises, the enclosing `with conn:` block rolls back
                # both the UPDATE above AND any partial INSERT.
                try:
                    inserted = cashflow_insert_one(cur, payload)
                except Exception:
                    raise

                deal_ref = inserted["deal_ref"]
                cur.execute(
                    "UPDATE bookings_draft "
                    "   SET approved_deal_ref = %s "
                    " WHERE id = %s "
                    "RETURNING *",
                    (deal_ref, draft_id),
                )
                return "ok", draft_db.row_to_public(cur, cur.fetchone()), deal_ref
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
