"""Insert one bookings_draft row for the acting user.

Stdin (server mode only):
  {"category": "CASHFLOW",
   "payload": {...the form-shape cashflow payload...},
   "client_request_id": "<uuid>",
   "_acting_user": "alice",
   "_auth_mode": "cookie" | "bearer"}

A Bearer caller may add "requested_by": "<mo username>" inside the payload
to book on that user's behalf (the draft's user_id); created_by stays the
token owner.

Stdout success: {"ok": true, "row": {...public fields...}, "deduped": false}
Stdout failure: {"ok": false, "error": "..."}

If the client_request_id already exists, the existing row is returned
with "deduped": true (HTTP 200, not 409 — idempotent retry).
"""
from __future__ import annotations
from datetime import datetime, timezone
import json
import sys
import uuid

import account_id_resolve
import draft_db
import scope
from cashflow_insert import _insert_one as _cashflow_insert_one
from spot_insert import _insert_one as _spot_insert_one
import transfer_db
import transfer_insert


def _transfer_insert_pair(cur, payload):
    """Book a TRANSFER draft the way /api/transfer/insert does: the leg as
    booked plus its INTERNAL mirror (unless _meta.mirror is false), ids
    stamped from refdata. The draft links to the booked leg; the mirror's
    ref rides on the payload so approve / reject move both legs together."""
    transfer_db.stamp_account_ids(payload)
    meta = payload.get("_meta") if isinstance(payload.get("_meta"), dict) else {}
    legs = [payload]
    if payload.get("transfer_type") == "INTERNAL" and meta.get("mirror", True) is not False:
        legs = transfer_db.pair_legs(payload)
    rows = [transfer_insert._insert_one(cur, leg) for leg in legs]
    if len(rows) > 1:
        payload.setdefault("_meta", {})["mirror_deal_ref"] = rows[1]["deal_ref"]
    payload.setdefault("_meta", {})["_booked_rows"] = rows
    return rows[0]


# The trade row is created at BOOKING time now, not on approval. Same
# inserters draft_approve used to call — identical validation, just earlier.
# `approved_deal_ref` on the draft carries the ref: the column predates this
# flow and its name now reads oddly (it is set at creation, not approval),
# but it is the link and nothing else consumes it beforehand.
_INSERTERS = {
    "CASHFLOW": _cashflow_insert_one,
    "SPOT": _spot_insert_one,
    "TRANSFER": _transfer_insert_pair,
}


def mirror_request_id(client_request_id: str) -> str:
    """client_request_id for the mirror leg's draft of an INTERNAL transfer.

    Derived from the caller's id, not generated, so a retried booking lands
    on the same pair of drafts and the UNIQUE constraint dedupes both.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL,
                          "tokka-mo:mirror-draft:" + str(client_request_id)))


def mirror_draft_payload(booked_rows) -> dict | None:
    """The draft payload for the mirror leg, from the row as inserted, or
    None when the booking has no mirror (EXTERNAL, or _meta.mirror false).

    The payload is the mirror's own columns -- the ends swapped, the
    direction flipped, the ids transfer_db stamped -- without the enquiry
    aliases row_to_payload adds, so the Approvals page can open it in the
    form and draft_patch validates it like any other TRANSFER draft.
    """
    if not isinstance(booked_rows, list) or len(booked_rows) < 2:
        return None
    mirror = booked_rows[1] or {}
    return {c: mirror.get(c) for c in transfer_db.DATA_COLUMNS if c != "deal_ref"}


_DRAFT_INSERT_SQL = (
    "INSERT INTO bookings_draft "
    "(category, payload, source, status, batch_id, "
    " client_request_id, created_by, approved_deal_ref) "
    "VALUES (%s, %s, 'CLAUDE_CODE', 'PENDING_REVIEW', %s, %s, %s, %s) "
    "RETURNING *"
)


def insert_draft_rows(cur, category, payload, crid, acting, deal_ref,
                      booked_rows, batch_id=None):
    """INSERT the draft(s) for one booking; returns [primary, mirror?] public rows.

    One draft per live row. An INTERNAL transfer books two legs (the leg as
    booked plus its mirror on the receiving account), so it gets two drafts,
    one per leg, the way the transfer book itself shows two rows. The pair is
    cross-linked through _meta.mirror_deal_ref / _meta.mirror_draft_id so
    approving or rejecting either card settles both legs and both drafts.
    """
    mirror = mirror_draft_payload(booked_rows) if category == "TRANSFER" else None
    cur.execute(_DRAFT_INSERT_SQL,
                (category, json.dumps(payload), batch_id, crid, acting, deal_ref))
    primary = draft_db.row_to_public(cur, cur.fetchone())
    if mirror is None:
        return [primary]
    mirror["_meta"] = {"mirror_deal_ref": deal_ref, "mirror_draft_id": primary["id"]}
    mirror_ref = (booked_rows[1] or {}).get("deal_ref")
    cur.execute(_DRAFT_INSERT_SQL,
                (category, json.dumps(mirror), batch_id, mirror_request_id(crid),
                 acting, mirror_ref))
    second = draft_db.row_to_public(cur, cur.fetchone())
    linked = dict(payload)
    linked["_meta"] = {**(linked.get("_meta") or {}), "mirror_draft_id": second["id"]}
    cur.execute(
        "UPDATE bookings_draft SET payload = %s WHERE id = %s RETURNING *",
        (json.dumps(linked), primary["id"]),
    )
    return [draft_db.row_to_public(cur, cur.fetchone()), second]


def apply_transfer_time_defaults(payload, now_iso: str) -> dict:
    """Fill a TRANSFER draft's times the way the bot's users expect.

    A transfer booked through Colossus is almost always booked after the
    fact, so a missing completed_datetime means "same moment as initiated",
    not "still in flight" (Danny, 2026-10-07). A missing initiated_datetime
    is now. The web form is untouched: there a blank completed time is the
    operator saying the movement has not landed.
    """
    if not isinstance(payload, dict):
        return payload
    out = dict(payload)
    if not str(out.get("initiated_datetime") or "").strip():
        out["initiated_datetime"] = now_iso
    if not str(out.get("completed_datetime") or "").strip():
        out["completed_datetime"] = out["initiated_datetime"]
    return out


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
    # A draft is a booking in waiting, so it is gated like one: you cannot
    # queue a trade for a portfolio you do not own.
    scope.check_write(scope.read_scope(payload_in),
                      (payload or {}).get("portfolio_id")
                      if isinstance(payload, dict) else None)
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
    # `requested_by` (Bearer callers only) names who the draft is booked
    # for; created_by below keeps the token owner. See draft_db.resolve_booker.
    booker, payload = draft_db.resolve_booker(
        payload, acting, payload_in.get("_auth_mode"))
    if isinstance(payload, dict):
        now_iso = datetime.now(timezone.utc).isoformat()
        defaults = {"user_id": f"claude:{booker}"}
        if _is_missing_or_midnight(payload.get("trade_date")):
            defaults["trade_date"] = now_iso
        if _is_missing_or_midnight(payload.get("value_date")):
            defaults["value_date"] = now_iso
        payload = {**payload, **defaults}
        if category == "TRANSFER":
            payload = apply_transfer_time_defaults(payload, now_iso)
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

                # Book the live trade NOW, as PENDING, on the same cursor.
                # The trade is visible in Deal Enquiry, the exports and the
                # position feed before anyone approves it — that is the
                # point of this flow. Approval and rejection move this row
                # rather than creating one.
                #
                # Same transaction as the draft insert, so a failure in
                # either leaves neither: there is no window where a draft
                # exists without its trade, or vice versa.
                deal_ref = None
                booked_rows = []
                inserter = _INSERTERS.get(category)
                if inserter is not None:
                    # Stamp the gateway account_id here too. The insert
                    # scripts do it in main(), which this path bypasses by
                    # calling _insert_one directly — without it every
                    # bot-booked trade would land with a NULL account_id.
                    # A transfer has two ends and stamps its own.
                    if category != "TRANSFER":
                        account_id_resolve.stamp(payload)
                    inserted = inserter(cur, payload)
                    deal_ref = inserted.get("deal_ref")
                    if isinstance(payload.get("_meta"), dict):
                        booked_rows = payload["_meta"].pop("_booked_rows", [])

                drafts = insert_draft_rows(cur, category, payload, crid, acting,
                                           deal_ref, booked_rows)
                public = drafts[0]
                if len(drafts) > 1:
                    public = {**public, "mirror": drafts[1]}
        # After the MO commit: the tech-DB mirror a direct transfer insert
        # would have written. Best-effort, never fails the draft.
        if category == "TRANSFER" and booked_rows:
            transfer_insert._dual_write_manual_transfer(booked_rows)
        return public, False
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
    except scope.ScopeError as e:
        print(json.dumps(scope.refusal(e)))
        return 3
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
