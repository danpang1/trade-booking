"""Insert one bookings_draft row for the acting user.

Stdin (server mode only):
  {"category": "CASHFLOW",
   "payload": {...the form-shape cashflow payload...},
   "client_request_id": "<uuid>",
   "_acting_user": "alice"}

Stdout success: {"ok": true, "row": {...public fields...}, "deduped": false}
Stdout failure: {"ok": false, "error": "..."}

If the client_request_id already exists, the existing row is returned
with "deduped": true (HTTP 200, not 409 — idempotent retry).
"""
from __future__ import annotations
from datetime import datetime, timezone
import json
import sys

import draft_db


def _is_missing_or_midnight(v) -> bool:
    """True if v is empty, or parses to a datetime at exact 00:00:00 UTC."""
    if not v:
        return True
    if not isinstance(v, str):
        return False
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        # "2026-05-27" (date-only) doesn't have a time component → treat as midnight
        try:
            datetime.strptime(v, "%Y-%m-%d")
            return True
        except ValueError:
            return False
    return dt.hour == 0 and dt.minute == 0 and dt.second == 0 and dt.microsecond == 0


def _insert(payload_in: dict) -> tuple[dict, bool]:
    category = draft_db.validate_category(payload_in.get("category"))
    payload = payload_in.get("payload")
    crid = draft_db.validate_uuid(payload_in.get("client_request_id"))
    acting = payload_in.get("_acting_user")
    if not isinstance(acting, str) or not acting:
        raise draft_db.ValidationError("missing _acting_user (server bug)")

    # Stamp user_id inside the payload so the eventual cashflow_insert
    # writes the right user. Prefix with "claude:" so any downstream
    # row (live trade after approve, draft displayed in the form) is
    # attributed to the Claude Code booking path — drafts only exist
    # because Claude Code (or the plugin) submitted them.
    # Also default trade_date / value_date to the draft creation time
    # when missing OR when supplied as exact UTC midnight. The midnight
    # case catches CLI/agent submissions that strip the time component
    # ("2026-05-27T00:00:00+00:00"); the user wants those to reflect
    # the actual moment of submission, not 00:00 of the day.
    if isinstance(payload, dict):
        now_iso = datetime.now(timezone.utc).isoformat()
        defaults = {"user_id": f"claude:{acting}"}
        if _is_missing_or_midnight(payload.get("trade_date")):
            defaults["trade_date"] = now_iso
        if _is_missing_or_midnight(payload.get("value_date")):
            defaults["value_date"] = now_iso
        payload = {**payload, **defaults}
    # Shape validation against the live cashflow_db rules — same code
    # path the form's POST /api/cashflow/insert uses.
    draft_db.validate_payload_for_category(category, payload)

    conn = draft_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                # Dedupe: if a draft already exists for this client_request_id,
                # return it unchanged. UNIQUE constraint enforces this at DB
                # level too, but checking first avoids an exception path.
                cur.execute(
                    "SELECT * FROM bookings_draft WHERE client_request_id = %s",
                    (crid,),
                )
                existing = cur.fetchone()
                if existing is not None:
                    return draft_db.row_to_public(cur, existing), True

                cur.execute(
                    "INSERT INTO bookings_draft "
                    "(category, payload, source, status, "
                    " client_request_id, created_by) "
                    "VALUES (%s, %s, 'CLAUDE_CODE', 'PENDING_REVIEW', %s, %s) "
                    "RETURNING *",
                    (category, json.dumps(payload), crid, acting),
                )
                return draft_db.row_to_public(cur, cur.fetchone()), False
    finally:
        conn.close()


def main() -> int:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig").strip() or "{}"
        body = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2

    try:
        row, deduped = _insert(body)
    except draft_db.ValidationError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5

    print(json.dumps({"ok": True, "row": row, "deduped": deduped}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
