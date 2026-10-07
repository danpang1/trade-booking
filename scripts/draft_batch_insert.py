"""Insert N bookings_draft rows for the acting user, atomically.

Stdin:
  {"trades": [
     {"category": "CASHFLOW", "payload": {...}, "client_request_id": "<uuid>"},
     ...
   ],
   "_acting_user": "alice",
   "_auth_mode": "cookie" | "bearer"}

A Bearer caller may add "requested_by": "<mo username>" inside any payload
to book that trade on the named user's behalf (see draft_insert.py).

Stdout success: {"ok": true, "batch_id": "<uuid>", "created": N, "rows": [...],
                 "mirrors": [...]}
  `rows` is one draft per trade sent, in order. An INTERNAL transfer also
  books its mirror leg, whose own draft is listed under `mirrors`.
Stdout failure: {"ok": false, "error": "..."}

If any single trade fails validation, the WHOLE batch rolls back
(no rows inserted). Dedupe is per-trade: if a client_request_id
already exists, that row is returned unchanged AND counted in 'created'
under its existing batch_id (a new batch_id is only allocated for
genuinely new rows in this call).
"""
from __future__ import annotations
from datetime import datetime, timezone
import json
import sys
import uuid

import account_id_resolve
import draft_db
import scope
import draft_insert
from draft_insert import _is_missing_or_midnight


def _insert_batch(body: dict) -> dict:
    acting = body.get("_acting_user")
    if not isinstance(acting, str) or not acting:
        raise draft_db.ValidationError("missing _acting_user (server bug)")
    auth_mode = body.get("_auth_mode")
    trades = body.get("trades")
    if not isinstance(trades, list) or not trades:
        raise draft_db.ValidationError("'trades' must be a non-empty list")
    if len(trades) > 50:
        raise draft_db.ValidationError("batch too large (max 50 trades)")

    # Pre-validate everything BEFORE opening a txn so all errors surface
    # without holding locks. The DB UNIQUE constraint on client_request_id
    # backs this up at write time.
    ptf = scope.read_scope(body)
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
        # Every trade in the batch, not just the first: an inter-PTF pair
        # books two legs in two portfolios and both must be the caller's.
        try:
            scope.check_write(ptf, payload.get("portfolio_id")
                              if isinstance(payload, dict) else None)
        except scope.ScopeError as e:
            raise scope.ScopeError(f"trade {i}: {e}") from e
        # Stamp user_id with "claude:" prefix so the row's booker is
        # attributed to the Claude Code path (see draft_insert.py).
        # Also default trade_date / value_date to now (UTC) when missing
        # OR when supplied as exact UTC midnight — see draft_insert.py
        # for the rationale.
        # Per-trade on-behalf-of (Bearer callers only) — see draft_db.resolve_booker.
        try:
            booker, payload = draft_db.resolve_booker(payload, acting, auth_mode)
        except draft_db.ValidationError as e:
            raise draft_db.ValidationError(f"trade {i}: {e}") from e
        if isinstance(payload, dict):
            now_iso = datetime.now(timezone.utc).isoformat()
            defaults = {"user_id": f"claude:{booker}"}
            if _is_missing_or_midnight(payload.get("trade_date")):
                defaults["trade_date"] = now_iso
            if _is_missing_or_midnight(payload.get("value_date")):
                defaults["value_date"] = now_iso
            payload = {**payload, **defaults}
            if cat == "TRANSFER":
                payload = draft_insert.apply_transfer_time_defaults(payload, now_iso)
        draft_db.validate_payload_for_category(cat, payload)
        prepared.append((cat, payload, crid))

    batch_id = str(uuid.uuid4())
    out_rows = []
    mirrors = []
    all_booked = []
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
                        cur.execute(
                            "SELECT * FROM bookings_draft WHERE client_request_id = %s",
                            (draft_insert.mirror_request_id(crid),),
                        )
                        twin = cur.fetchone()
                        if twin is not None:
                            mirrors.append(draft_db.row_to_public(cur, twin))
                        continue
                    # Book the live trade as PENDING alongside the draft, on
                    # the same cursor. The batch is already all-or-nothing, so
                    # a failure on any leg leaves no drafts AND no trades —
                    # which matters most for an inter-PTF pair, where half a
                    # transfer in the book is worse than none.
                    deal_ref = None
                    booked_rows = []
                    inserter = draft_insert._INSERTERS.get(cat)
                    if inserter is not None:
                        # A transfer has two ends and stamps its own ids.
                        if cat != "TRANSFER":
                            account_id_resolve.stamp(payload)
                        deal_ref = inserter(cur, payload).get("deal_ref")
                        if isinstance(payload.get("_meta"), dict):
                            booked_rows = payload["_meta"].pop("_booked_rows", [])
                    drafts = draft_insert.insert_draft_rows(
                        cur, cat, payload, crid, acting, deal_ref, booked_rows,
                        batch_id=batch_id)
                    out_rows.append(drafts[0])
                    mirrors.extend(drafts[1:])
                    if cat == "TRANSFER" and booked_rows:
                        all_booked.extend(booked_rows)
    finally:
        conn.close()
    # After the MO commit: the tech-DB mirror a direct transfer insert
    # would have written. Best-effort, never fails the batch.
    if all_booked:
        import transfer_insert
        transfer_insert._dual_write_manual_transfer(all_booked)

    return {
        "ok": True,
        "batch_id": batch_id,
        "created": len(out_rows),
        "rows": out_rows,
        "mirrors": mirrors,
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
    except scope.ScopeError as e:
        print(json.dumps(scope.refusal(e)))
        return 3
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
