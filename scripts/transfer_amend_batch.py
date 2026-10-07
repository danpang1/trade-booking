"""Bulk-amend transfer rows in ONE transaction (all-or-nothing).

stdin JSON: {"rows": [<amend payload>, ...]}
Each payload is a full transfer amend payload (same shape as
transfer_amend.py) plus an optional "expected_effective_start" (ISO string)
for optimistic concurrency: if the live row's effective_start no longer
matches, the whole batch aborts (the row was changed by someone else since
the client loaded it).

Each leg of an INTERNAL pair is its own deal_ref and amends on its own,
exactly as the single amend does; Transfer Enquiry selects legs, not pairs.

Writes JSON to stdout:
  Success:    {"ok": true, "rows": [...], "count": N}
  Conflict:   {"ok": false, "code": "conflict", "error": "...", "deal_ref": "..."}  (exit 4)
  Validation: {"ok": false, "error": "...", "deal_ref": "..."}                       (exit 3)

All-or-nothing: any failure rolls back every row -- nothing is written.
The route is admin-only (serverScope.mjs); the transfer book has no
portfolio column, so nothing here consults scope.
"""
from __future__ import annotations
import json
import sys

import authorship
import transfer_db


class _BatchConflict(Exception):
    """A selected row is no longer the live version -- abort the whole batch."""

    def __init__(self, deal_ref, msg):
        super().__init__(msg)
        self.deal_ref = deal_ref


def prepare_rows(data):
    """Validate the request shape and every payload before any DB work.

    Returns the list of payloads, or raises transfer_db.ValidationError with
    the offending deal_ref on the exception (`.deal_ref`) when one row is bad.
    """
    rows = data.get("rows") if isinstance(data, dict) else (data if isinstance(data, list) else None)
    if not isinstance(rows, list) or len(rows) == 0:
        raise transfer_db.ValidationError("expected a non-empty 'rows' array")
    for i, p in enumerate(rows):
        if not isinstance(p, dict):
            raise transfer_db.ValidationError(f"row {i} is not an object")
        try:
            transfer_db.validate_payload(p, mode="amend")
        except transfer_db.ValidationError as e:
            err = transfer_db.ValidationError(str(e))
            err.deal_ref = p.get("deal_ref")
            raise err from e
    return rows


def _amend_one(cur, p):
    deal_ref = p["deal_ref"]
    expected = p.get("expected_effective_start")
    if expected:
        cur.execute(
            "UPDATE transfer SET effective_end = NOW() "
            "WHERE deal_ref = %s AND effective_end IS NULL "
            "AND effective_start = %s RETURNING deal_ref",
            (deal_ref, expected),
        )
    else:
        cur.execute(
            "UPDATE transfer SET effective_end = NOW() "
            "WHERE deal_ref = %s AND effective_end IS NULL "
            "RETURNING deal_ref",
            (deal_ref,),
        )
    if cur.fetchone() is None:
        raise _BatchConflict(
            deal_ref,
            f"{deal_ref} is not the current live row (changed or removed "
            f"since the page loaded) -- batch aborted, nothing changed",
        )
    # Re-resolve an own-side id only where it is blank, so a corrected
    # account gets its id and a hand-corrected id is kept.
    transfer_db.stamp_account_ids(p)
    # Created By stays the original booker; the amender moves to updated_by.
    authorship.apply_on_amend(cur, "transfer", p, deal_ref)
    cols, vals = transfer_db.payload_to_columns(p, deal_ref=deal_ref)
    col_list = ", ".join(cols + ("effective_start", "effective_end"))
    placeholders = ", ".join(["%s"] * len(cols)) + ", NOW(), NULL"
    cur.execute(
        f"INSERT INTO transfer ({col_list}) VALUES ({placeholders}) RETURNING *",
        vals,
    )
    out_cols = [d.name for d in cur.description]
    return transfer_db.row_to_payload(out_cols, cur.fetchone())


def _dual_write_manual_transfer_amend_batch(out_rows: list) -> None:
    """Best-effort manual_transfer mirror for each amended row (SCD2
    supersede). Runs post-commit; never affects the primary batch amend."""
    try:
        import manual_write

        for row in out_rows:
            manual_write.write_manual_transfer_amend(row)
    except Exception as e:  # noqa: BLE001
        print(f"manual dual-write: skip manual_transfer amend batch: {e!r}", file=sys.stderr)


def main() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2

    try:
        rows = prepare_rows(data)
    except transfer_db.ValidationError as e:
        print(json.dumps({"ok": False, "error": str(e), "deal_ref": getattr(e, "deal_ref", None)}))
        return 3

    conn = transfer_db.connect()
    out_rows = []
    try:
        with conn:
            with conn.cursor() as cur:
                for p in rows:
                    out_rows.append(_amend_one(cur, p))
        print(json.dumps({"ok": True, "rows": out_rows, "count": len(out_rows)}))
        _dual_write_manual_transfer_amend_batch(out_rows)
        return 0
    except _BatchConflict as e:
        print(json.dumps({"ok": False, "code": "conflict", "error": str(e), "deal_ref": e.deal_ref}))
        return 4
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
