# Claude Code Trade Booking — Phase 1a: CASHFLOW Drafts (Server + UI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the end-to-end CASHFLOW draft loop on the server and React app. A user (or any Bearer-auth client) submits a CASHFLOW booking — single or N-row batch — as a draft. The same user reviews drafts at `/pending`, edits if needed (in-place modal **or** the full booking form via "Open in form"), then approves; approval atomically inserts into `trades_cashflow` via the existing `cashflow_insert._insert_one` path. The Claude Code plugin itself ships in a separate Plan 1b.

**Architecture:** New `bookings_draft` table holds JSONB `payload` per category; live trade tables (`trades_cashflow`) are unchanged. Seven new `/api/bookings/draft(s)` endpoints accept cookie OR Bearer auth. Per-user isolation enforced server-side on every list/get/patch/approve/reject (`WHERE created_by = req.sessionUser.username`). Approve uses one BEGIN/COMMIT that claims the draft AND calls `cashflow_insert._insert_one(cur, payload)` in-process — atomic, no compensating logic. New `<PendingDrafts>` React page mounts via a new `appView === "pending"` branch; `TradeBookingForm.jsx` gains a third mode (`draft`) driven by `?draft=<id>` in the URL.

**Tech Stack:** Postgres (`MO_DB_UAT`), Python 3.10+ with `psycopg2`, Node.js HTTP server (no framework), React 19 + Vite, `lucide-react` icons.

**Reference:** [Design doc](../design/2026-05-23-claude-code-trade-booking-design.md). This plan implements **Section 4.1 (bookings_draft table)**, **Section 5.3 (draft endpoints)**, and **Sections 6.1 + 6.3 (PendingDrafts page + form draft mode)** of the spec. The Claude Code plugin (Section 7) is deferred to Plan 1b.

---

## File Structure

**Created (10 Python):**
- `scripts/apply_schema_drafts.py` — idempotent DDL applier, parallels `apply_schema_api_tokens.py`
- `scripts/draft_db.py` — pure logic (validators, dedupe key gen) + DB connect helper
- `scripts/draft_insert.py` — POST handler (single)
- `scripts/draft_batch_insert.py` — POST handler (batch, atomic)
- `scripts/draft_list.py` — GET handler with `status` + `batch_id` filters
- `scripts/draft_get.py` — GET single by id
- `scripts/draft_patch.py` — PATCH payload (only `PENDING_REVIEW`)
- `scripts/draft_approve.py` — atomic claim + `cashflow_insert._insert_one` in-process
- `scripts/draft_reject.py` — soft reject with optional reason
- `scripts/smoke_drafts.py` — end-to-end smoke
- `tests/test_draft_db.py` — pure-logic unit tests

**Created (2 React):**
- `src/pending/PendingDrafts.jsx` — drafts inbox; batch grouping; approve-all
- `src/pending/DraftEditModal.jsx` — in-place edit modal (key fields only)

**Modified (3):**
- `server.js` — 3 new script constants + 7 routes under `/api/bookings/draft(s)`
- `src/auth/api.js` — 7 new draft helpers
- `src/TradeBookingForm.jsx` — `appView === "pending"` mount; sidebar nav with PENDING badge; `draftId` state + `?draft=<id>` URL effect + draft-mode submit handler + button labels

**Untouched (explicitly):**
- `trades_cashflow`, `trades_spot`, `trades_loan`, `users`, `sessions`, `api_tokens` — zero schema changes
- `cashflow_insert.py`, `cashflow_amend.py`, `cashflow_db.py` — zero changes; `_insert_one` is imported in-process by `draft_approve.py`
- All `spot_*.py` and `loan_*.py` scripts — Phase 2/later
- The Claude Code plugin (separate repo, Plan 1b)

---

## Task 1: Schema migration for `bookings_draft`

**Goal:** Create the `bookings_draft` table on UAT.

**Files:**
- Create: `scripts/apply_schema_drafts.py`

**Acceptance Criteria:**
- [ ] Running `python scripts/apply_schema_drafts.py` exits 0 and prints `ok: bookings_draft table ready`
- [ ] Table has columns id, category, payload, source, status, batch_id, client_request_id, created_by, created_at, updated_at, approved_at, approved_by, approved_deal_ref, rejected_at, rejected_by, rejection_reason

**Verify:** `python scripts/apply_schema_drafts.py` → `ok: bookings_draft table ready`

**Steps:**

- [ ] **Step 1: Create the schema applier**

Pattern lifted from `scripts/apply_schema_api_tokens.py` — reuse `cashflow_db.connect()`, run DDL with `CREATE TABLE IF NOT EXISTS` so it's idempotent.

Create `scripts/apply_schema_drafts.py`:

```python
"""Create `bookings_draft` table. Idempotent."""
from __future__ import annotations
import cashflow_db

DDL = """
CREATE TABLE IF NOT EXISTS bookings_draft (
  id                  SERIAL          PRIMARY KEY,
  category            TEXT            NOT NULL
                        CHECK (category IN ('SPOT','CASHFLOW')),
  payload             JSONB           NOT NULL,
  source              TEXT            NOT NULL
                        CHECK (source IN ('CLAUDE_CODE')),
  status              TEXT            NOT NULL
                        CHECK (status IN
                          ('PENDING_REVIEW','APPROVED','REJECTED')),
  batch_id            UUID,
  client_request_id   UUID            NOT NULL UNIQUE,
  created_by          VARCHAR(64)     NOT NULL,
  created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
  approved_at         TIMESTAMPTZ,
  approved_by         VARCHAR(64),
  approved_deal_ref   TEXT,
  rejected_at         TIMESTAMPTZ,
  rejected_by         VARCHAR(64),
  rejection_reason    TEXT
);

CREATE INDEX IF NOT EXISTS idx_drafts_user_status
  ON bookings_draft (created_by, status);

CREATE INDEX IF NOT EXISTS idx_drafts_batch
  ON bookings_draft (batch_id)
  WHERE batch_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_drafts_pending
  ON bookings_draft (created_by, created_at DESC)
  WHERE status = 'PENDING_REVIEW';
"""


def main() -> None:
    conn = cashflow_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(DDL)
        print("ok: bookings_draft table ready")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Apply against UAT**

Run: `python scripts/apply_schema_drafts.py`
Expected output: `ok: bookings_draft table ready`

- [ ] **Step 3: Verify the table and indexes exist**

Run:
```bash
python -c "
import sys; sys.path.insert(0, 'scripts')
import cashflow_db
conn = cashflow_db.connect()
with conn.cursor() as cur:
    cur.execute(\"SELECT column_name FROM information_schema.columns WHERE table_name='bookings_draft' ORDER BY ordinal_position\")
    print('cols:', [r[0] for r in cur.fetchall()])
    cur.execute(\"SELECT indexname FROM pg_indexes WHERE tablename='bookings_draft' ORDER BY indexname\")
    print('idx :', [r[0] for r in cur.fetchall()])
"
```
Expected:
```
cols: ['id', 'category', 'payload', 'source', 'status', 'batch_id', 'client_request_id', 'created_by', 'created_at', 'updated_at', 'approved_at', 'approved_by', 'approved_deal_ref', 'rejected_at', 'rejected_by', 'rejection_reason']
idx : ['bookings_draft_client_request_id_key', 'bookings_draft_pkey', 'idx_drafts_batch', 'idx_drafts_pending', 'idx_drafts_user_status']
```

- [ ] **Step 4: Commit**

```bash
git add scripts/apply_schema_drafts.py
git commit -m "feat(drafts): add bookings_draft schema for Phase 1a"
```

---

## Task 2: `draft_db.py` — pure logic + helpers (TDD)

**Goal:** Validators (category, status, UUID, payload-by-category) + DB connect helper, all DB-free for unit testing.

**Files:**
- Create: `scripts/draft_db.py`
- Test: `tests/test_draft_db.py`

**Acceptance Criteria:**
- [ ] All tests in `tests/test_draft_db.py` pass
- [ ] flake8 clean using the project's existing ignore list

**Verify:** `python -m pytest tests/test_draft_db.py -v` → all PASS

**Steps:**

- [ ] **Step 1: Write the failing tests**

Create `tests/test_draft_db.py`:

```python
"""Pure-logic unit tests for draft_db. No DB connection required."""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pytest  # noqa: E402
import draft_db  # noqa: E402


# ── Category validation ─────────────────────────────────────────────

def test_validate_category_accepts_cashflow():
    assert draft_db.validate_category("CASHFLOW") == "CASHFLOW"


def test_validate_category_accepts_spot():
    # SPOT is allowed at the DB level; Plan 1a only routes CASHFLOW.
    assert draft_db.validate_category("SPOT") == "SPOT"


@pytest.mark.parametrize("bad", ["cashflow", "", None, "OTHER", 123])
def test_validate_category_rejects(bad):
    with pytest.raises(draft_db.ValidationError):
        draft_db.validate_category(bad)


# ── client_request_id validation ────────────────────────────────────

def test_validate_uuid_accepts_canonical():
    s = "11111111-2222-3333-4444-555555555555"
    assert draft_db.validate_uuid(s) == s


def test_validate_uuid_accepts_generated():
    s = str(uuid.uuid4())
    assert draft_db.validate_uuid(s) == s


@pytest.mark.parametrize("bad", ["", None, "not-a-uuid", "12345", 42])
def test_validate_uuid_rejects(bad):
    with pytest.raises(draft_db.ValidationError):
        draft_db.validate_uuid(bad)


# ── Status set ──────────────────────────────────────────────────────

def test_statuses_constant_is_complete():
    assert draft_db.STATUSES == ("PENDING_REVIEW", "APPROVED", "REJECTED")


# ── Payload shape gate (calls cashflow_db.validate_payload) ─────────

def test_validate_payload_for_category_cashflow_passes_through():
    """For CASHFLOW, draft_db delegates to cashflow_db.validate_payload(mode='insert').
    A complete CASHFLOW payload should not raise.
    """
    payload = {
        "cashflow_type": "FUNDING IN",
        "direction": "INCOMING",
        "entity": "TK006",
        "portfolio_id": 8006,
        "portfolio_name": "CDA",
        "counterparty": "Galaxy",
        "asset": "USDC",
        "amount": "1.00",
        "trade_date": "2026-05-15T12:00:00+00:00",
        "value_date": "2026-05-15T12:00:00+00:00",
        "user_id": "test",
        "status": "PENDING",
    }
    draft_db.validate_payload_for_category("CASHFLOW", payload)  # no raise


def test_validate_payload_for_category_cashflow_missing_field_raises():
    bad = {"cashflow_type": "FUNDING IN"}  # missing many required
    with pytest.raises(draft_db.ValidationError):
        draft_db.validate_payload_for_category("CASHFLOW", bad)


def test_validate_payload_for_category_spot_not_implemented_in_phase_1a():
    """Plan 1a is CASHFLOW-only. SPOT is accepted at DB level but the
    endpoint must reject it cleanly. validate_payload_for_category
    raises a clear error for SPOT until Phase 2 wires spot_db."""
    with pytest.raises(draft_db.ValidationError, match="SPOT"):
        draft_db.validate_payload_for_category("SPOT", {})


# ── row_to_public ───────────────────────────────────────────────────

def test_row_to_public_omits_internal_fields_and_isoformats_dates():
    """row_to_public maps a SELECT-* row to the API JSON payload.
    Internal-only columns aren't omitted (drafts have nothing secret),
    but datetimes must be JSON-safe (ISO 8601 strings)."""
    import datetime as dt

    class FakeCol:
        def __init__(self, name): self.name = name

    class FakeCur:
        description = [FakeCol(n) for n in (
            "id", "category", "payload", "status", "batch_id",
            "client_request_id", "created_by", "created_at",
            "updated_at", "approved_at", "approved_by",
            "approved_deal_ref", "rejected_at", "rejected_by",
            "rejection_reason",
        )]

    row = (
        42, "CASHFLOW", {"a": 1}, "PENDING_REVIEW", None,
        "00000000-0000-0000-0000-000000000001", "alice",
        dt.datetime(2026, 5, 25, 10, 0, 0, tzinfo=dt.timezone.utc),
        dt.datetime(2026, 5, 25, 10, 0, 0, tzinfo=dt.timezone.utc),
        None, None, None, None, None, None,
    )
    out = draft_db.row_to_public(FakeCur(), row)
    assert out["id"] == 42
    assert out["category"] == "CASHFLOW"
    assert out["payload"] == {"a": 1}
    assert out["status"] == "PENDING_REVIEW"
    assert out["created_by"] == "alice"
    assert out["created_at"].startswith("2026-05-25T10:00:00")
    assert out["approved_at"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_draft_db.py -v`
Expected: All tests FAIL with `ModuleNotFoundError: No module named 'draft_db'`

- [ ] **Step 3: Implement `draft_db.py`**

Create `scripts/draft_db.py`:

```python
"""Shared helper for draft_* endpoint scripts.

Pure-logic functions (validate_category, validate_uuid, validate_payload_for_category,
row_to_public) live here and are exercised by tests/test_draft_db.py without
touching the DB. DB-touching functions reuse cashflow_db.connect.
"""
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
import uuid as _uuid

import cashflow_db


# ── Constants ──────────────────────────────────────────────────────

CATEGORIES = ("CASHFLOW", "SPOT")
STATUSES = ("PENDING_REVIEW", "APPROVED", "REJECTED")
SOURCES = ("CLAUDE_CODE",)


class ValidationError(ValueError):
    """Raised by validate_* helpers; caught in main() and rendered as JSON."""


# ── Validators ─────────────────────────────────────────────────────

def validate_category(c) -> str:
    if not isinstance(c, str) or c not in CATEGORIES:
        raise ValidationError(f"category must be one of {CATEGORIES}, got {c!r}")
    return c


def validate_uuid(s) -> str:
    if not isinstance(s, str) or not s:
        raise ValidationError("uuid must be a non-empty string")
    try:
        _uuid.UUID(s)
    except (ValueError, AttributeError, TypeError) as e:
        raise ValidationError(f"invalid uuid: {s!r}") from e
    return s


def validate_payload_for_category(category: str, payload) -> None:
    """Delegate to the relevant *_db validator. Phase 1a wires CASHFLOW only;
    SPOT is intentionally unimplemented and will raise here until Phase 2.
    """
    if category == "CASHFLOW":
        try:
            cashflow_db.validate_payload(payload, mode="insert")
        except cashflow_db.ValidationError as e:
            raise ValidationError(str(e)) from e
        return
    if category == "SPOT":
        raise ValidationError("SPOT drafts not yet supported (Plan 1a is CASHFLOW only)")
    raise ValidationError(f"unknown category: {category!r}")


# ── DB-touching ────────────────────────────────────────────────────

def connect():
    """Reuse the MO_DB_UAT connection used by cashflow scripts."""
    return cashflow_db.connect()


# Columns returned to the API consumer. (Drafts have no secrets, but we
# keep the mapping centralized so date isoformat is consistent.)
PUBLIC_COLUMNS = (
    "id", "category", "payload", "status", "batch_id",
    "client_request_id", "created_by", "created_at", "updated_at",
    "approved_at", "approved_by", "approved_deal_ref",
    "rejected_at", "rejected_by", "rejection_reason",
)


def _json_safe(v):
    if isinstance(v, Decimal):
        return format(v.normalize(), "f") if v == v.to_integral_value() else str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, _uuid.UUID):
        return str(v)
    return v


def row_to_public(cur, row) -> dict:
    """Map a SELECT-* row to the API JSON payload."""
    cols = [d.name for d in cur.description]
    return {
        c: _json_safe(v)
        for c, v in zip(cols, row)
        if c in PUBLIC_COLUMNS
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_draft_db.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Lint**

Run: `flake8 --max-line-length=88 --ignore=E203,W503,E501,F841,F401,E722,F541,F811,E262,C901 scripts/draft_db.py tests/test_draft_db.py`
Expected: no output (clean).

- [ ] **Step 6: Commit**

```bash
git add scripts/draft_db.py tests/test_draft_db.py
git commit -m "feat(drafts): add draft_db pure-logic + tests"
```

---

## Task 3: `draft_insert.py` — create a single draft

**Goal:** POST /api/bookings/draft handler. Stamps `created_by` from session, validates payload shape with `cashflow_db.validate_payload`, dedupes on `client_request_id`.

**Files:**
- Create: `scripts/draft_insert.py`

**Acceptance Criteria:**
- [ ] A complete CASHFLOW payload + UUID returns `{"ok": true, "row": {...}}`
- [ ] A repeat with same `client_request_id` returns the existing row (no duplicate insert)
- [ ] An invalid payload returns `{"ok": false, "error": "..."}` and exit code 3
- [ ] `created_by` is the value of `_acting_user` from stdin (not the body)

**Verify:** Smoke commands in Step 2 below

**Steps:**

- [ ] **Step 1: Write the script**

Create `scripts/draft_insert.py`:

```python
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
import json
import sys

import draft_db


def _insert(payload_in: dict) -> tuple[dict, bool]:
    category = draft_db.validate_category(payload_in.get("category"))
    payload = payload_in.get("payload")
    crid = draft_db.validate_uuid(payload_in.get("client_request_id"))
    acting = payload_in.get("_acting_user")
    if not isinstance(acting, str) or not acting:
        raise draft_db.ValidationError("missing _acting_user (server bug)")

    # Stamp user_id inside the payload so the eventual cashflow_insert
    # writes the right user. The server already stamps _acting_user at
    # the outer level; we mirror it into payload.user_id here.
    if isinstance(payload, dict):
        payload = {**payload, "user_id": acting}
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
```

- [ ] **Step 2: Smoke test manually (use your own username)**

Generate a uuid:
```powershell
$U = [guid]::NewGuid().ToString()
echo $U
```

Submit a draft:
```powershell
$body = @"
{"category":"CASHFLOW","client_request_id":"$U","_acting_user":"<your_username>",
 "payload":{"cashflow_type":"FUNDING IN","direction":"INCOMING","entity":"TK006",
 "portfolio_id":8006,"portfolio_name":"CDA","counterparty":"Galaxy",
 "asset":"USDC","amount":"1.00","trade_date":"2026-05-25T12:00:00+00:00",
 "value_date":"2026-05-25T12:00:00+00:00","user_id":"placeholder","status":"PENDING"}}
"@
$body | python scripts/draft_insert.py
```
Expected: `{"ok": true, "row": {...}, "deduped": false}` — `row.id` and `row.created_at` populated.

Re-run with the same `$body`:
Expected: `{"ok": true, "row": {...}, "deduped": true}` — same `row.id`.

- [ ] **Step 3: Test invalid path**

```powershell
'{"category":"CASHFLOW","client_request_id":"00000000-0000-0000-0000-000000000999","_acting_user":"alice","payload":{}}' | python scripts/draft_insert.py
```
Expected: `{"ok": false, "error": "required field missing or empty: cashflow_type"}` and exit code 3.

- [ ] **Step 4: Commit**

```bash
git add scripts/draft_insert.py
git commit -m "feat(drafts): add draft_insert endpoint script (single)"
```

---

## Task 4: `draft_batch_insert.py` — atomic batch create

**Goal:** POST /api/bookings/draft/batch handler. Accepts `{trades: [{category, payload, client_request_id}, ...]}`. All-or-nothing: any validation failure rolls back the entire batch. All rows in a batch share one `batch_id` UUID.

**Files:**
- Create: `scripts/draft_batch_insert.py`

**Acceptance Criteria:**
- [ ] A 3-trade valid batch returns `{"ok": true, "batch_id": "...", "created": 3, "rows": [3 rows]}`
- [ ] A 3-trade batch where row 2 is invalid returns `{"ok": false, "error": "..."}` exit 3 and ZERO rows inserted (verifiable via SELECT)
- [ ] All 3 rows share the same `batch_id`
- [ ] Re-submitting the same batch (same client_request_ids) returns the existing rows (dedupe)

**Verify:** Smoke commands in Step 2 below

**Steps:**

- [ ] **Step 1: Write the script**

Create `scripts/draft_batch_insert.py`:

```python
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
```

- [ ] **Step 2: Smoke test — 3-trade happy path**

```powershell
$u1 = [guid]::NewGuid().ToString()
$u2 = [guid]::NewGuid().ToString()
$u3 = [guid]::NewGuid().ToString()
$base = '{"cashflow_type":"FUNDING IN","direction":"INCOMING","entity":"TK006","portfolio_id":8006,"portfolio_name":"CDA","counterparty":"Galaxy","asset":"USDC","amount":"1.00","trade_date":"2026-05-25T12:00:00+00:00","value_date":"2026-05-25T12:00:00+00:00","user_id":"placeholder","status":"PENDING"}'
$body = "{`"_acting_user`":`"<your_username>`",`"trades`":[" +
        "{`"category`":`"CASHFLOW`",`"client_request_id`":`"$u1`",`"payload`":$base}," +
        "{`"category`":`"CASHFLOW`",`"client_request_id`":`"$u2`",`"payload`":$base}," +
        "{`"category`":`"CASHFLOW`",`"client_request_id`":`"$u3`",`"payload`":$base}]}"
$body | python scripts/draft_batch_insert.py
```
Expected: `{"ok": true, "batch_id": "...", "created": 3, "rows": [...]}` — all 3 rows share the printed `batch_id`.

Verify in DB:
```bash
python -c "
import sys; sys.path.insert(0, 'scripts')
import draft_db
conn = draft_db.connect()
with conn.cursor() as cur:
    cur.execute(\"SELECT id, batch_id, status, payload->>'amount' FROM bookings_draft WHERE created_by=%s ORDER BY id DESC LIMIT 3\", ('<your_username>',))
    for r in cur.fetchall(): print(r)
"
```

- [ ] **Step 3: Smoke test — failure rolls back the batch**

```powershell
$u4 = [guid]::NewGuid().ToString()
$u5 = [guid]::NewGuid().ToString()
$bad = '{"cashflow_type":"FUNDING IN"}'  # missing required fields
$body = "{`"_acting_user`":`"<your_username>`",`"trades`":[" +
        "{`"category`":`"CASHFLOW`",`"client_request_id`":`"$u4`",`"payload`":$base}," +
        "{`"category`":`"CASHFLOW`",`"client_request_id`":`"$u5`",`"payload`":$bad}]}"
$body | python scripts/draft_batch_insert.py
```
Expected: `{"ok": false, "error": "required field missing or empty: direction"}` and exit 3.

Confirm no rows from this attempt landed (`$u4` should not appear):
```bash
python -c "
import sys; sys.path.insert(0, 'scripts')
import draft_db
conn = draft_db.connect()
with conn.cursor() as cur:
    cur.execute(\"SELECT id FROM bookings_draft WHERE client_request_id IN (%s, %s)\", ('<u4>', '<u5>'))
    print('rows:', cur.fetchall())
"
```
Expected: `rows: []`

- [ ] **Step 4: Commit**

```bash
git add scripts/draft_batch_insert.py
git commit -m "feat(drafts): add draft_batch_insert endpoint script (atomic)"
```

---

## Task 5: `draft_list.py` and `draft_get.py` — read endpoints

**Goal:** GET handlers — list user's drafts with optional `status`/`batch_id` filters; fetch a single draft by id. Both enforce `created_by = $acting`.

**Files:**
- Create: `scripts/draft_list.py`
- Create: `scripts/draft_get.py`

**Acceptance Criteria:**
- [ ] `draft_list.py` with no filter returns all of acting user's drafts, newest first
- [ ] `draft_list.py` with `status=PENDING_REVIEW` filters correctly
- [ ] `draft_list.py` with `batch_id=<uuid>` returns only that batch's rows
- [ ] `draft_get.py` with the acting user's draft id returns the row
- [ ] `draft_get.py` with another user's draft id returns `{"ok": false, "code": "not_found"}` exit 4

**Verify:** Smoke commands in Steps 2/4 below

**Steps:**

- [ ] **Step 1: Write `draft_list.py`**

Create `scripts/draft_list.py`:

```python
"""List bookings_draft rows owned by the acting user.

Stdin:
  {"_acting_user": "alice",
   "status": "PENDING_REVIEW" | "APPROVED" | "REJECTED" | null,
   "batch_id": "<uuid>" | null}

Stdout: {"ok": true, "drafts": [{...public...}, ...]}
"""
from __future__ import annotations
import json
import sys

import draft_db


def _list(acting: str, status, batch_id) -> list[dict]:
    where = ["created_by = %s"]
    args: list = [acting]
    if status is not None:
        if status not in draft_db.STATUSES:
            raise draft_db.ValidationError(
                f"status must be one of {draft_db.STATUSES}, got {status!r}"
            )
        where.append("status = %s")
        args.append(status)
    if batch_id is not None:
        draft_db.validate_uuid(batch_id)
        where.append("batch_id = %s")
        args.append(batch_id)

    sql = (
        "SELECT * FROM bookings_draft "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY created_at DESC"
    )

    conn = draft_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(args))
                rows = cur.fetchall()
                return [draft_db.row_to_public(cur, r) for r in rows]
    finally:
        conn.close()


def main() -> int:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig").strip() or "{}"
        body = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2

    acting = body.get("_acting_user")
    if not isinstance(acting, str) or not acting:
        print(json.dumps({"ok": False, "error": "missing _acting_user (server bug)"}))
        return 3

    try:
        drafts = _list(acting, body.get("status"), body.get("batch_id"))
    except draft_db.ValidationError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5

    print(json.dumps({"ok": True, "drafts": drafts}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke `draft_list.py`**

All of acting user's drafts:
```powershell
'{"_acting_user":"<your_username>"}' | python scripts/draft_list.py
```
Expected: `{"ok": true, "drafts": [...]}` — contains the rows you inserted in Tasks 3 and 4.

Filtered by status:
```powershell
'{"_acting_user":"<your_username>","status":"PENDING_REVIEW"}' | python scripts/draft_list.py
```
Expected: same set (all are pending so far).

Filtered by batch:
```powershell
'{"_acting_user":"<your_username>","batch_id":"<batch_id_from_task_4>"}' | python scripts/draft_list.py
```
Expected: exactly the 3 rows from that batch.

- [ ] **Step 3: Write `draft_get.py`**

Create `scripts/draft_get.py`:

```python
"""Fetch one bookings_draft row owned by the acting user.

Stdin: {"id": 42, "_acting_user": "alice"}
Stdout success: {"ok": true, "draft": {...public...}}
Stdout 404:     {"ok": false, "code": "not_found", "error": "draft not found"}

Drafts owned by other users return 404 (not 403) — avoids leaking
existence to unauthorized callers.
"""
from __future__ import annotations
import json
import sys

import draft_db


def _get(draft_id: int, acting: str) -> dict | None:
    conn = draft_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM bookings_draft "
                    "WHERE id = %s AND created_by = %s",
                    (draft_id, acting),
                )
                r = cur.fetchone()
                if r is None:
                    return None
                return draft_db.row_to_public(cur, r)
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
        draft = _get(draft_id, acting)
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5

    if draft is None:
        print(json.dumps({"ok": False, "code": "not_found", "error": "draft not found"}))
        return 4

    print(json.dumps({"ok": True, "draft": draft}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Smoke `draft_get.py`**

Replace `<DRAFT_ID>` with an id you saw in Task 3 output:
```powershell
'{"id":<DRAFT_ID>,"_acting_user":"<your_username>"}' | python scripts/draft_get.py
```
Expected: `{"ok": true, "draft": {...}}`.

Owned-by-someone-else 404:
```powershell
'{"id":<DRAFT_ID>,"_acting_user":"definitely_not_you"}' | python scripts/draft_get.py
```
Expected: `{"ok": false, "code": "not_found", "error": "draft not found"}` exit 4.

- [ ] **Step 5: Commit**

```bash
git add scripts/draft_list.py scripts/draft_get.py
git commit -m "feat(drafts): add draft_list and draft_get endpoint scripts"
```

---

## Task 6: `draft_patch.py` — edit a draft's payload

**Goal:** PATCH handler. Only allowed when `status='PENDING_REVIEW'` AND `created_by = $acting`. Re-validates payload using `cashflow_db.validate_payload`. Bumps `updated_at`.

**Files:**
- Create: `scripts/draft_patch.py`

**Acceptance Criteria:**
- [ ] Patching a pending draft replaces `payload` and bumps `updated_at`
- [ ] Patching an APPROVED draft returns `{"ok": false, "code": "conflict"}` exit code mapping to 409
- [ ] Patching another user's draft returns `not_found` 404
- [ ] Payload that fails validation returns 400-shape error, no DB write

**Verify:** Smoke in Step 2

**Steps:**

- [ ] **Step 1: Write the script**

Create `scripts/draft_patch.py`:

```python
"""Update the payload of a PENDING_REVIEW draft owned by the acting user.

Stdin: {"id": 42, "payload": {...new payload...}, "_acting_user": "alice"}

Stdout success:  {"ok": true, "row": {...public...}}
Stdout 404:      {"ok": false, "code": "not_found", "error": "draft not found"}
Stdout 409:      {"ok": false, "code": "conflict", "error": "draft is not PENDING_REVIEW"}
Stdout 400:      {"ok": false, "error": "<validation>"}
"""
from __future__ import annotations
import json
import sys

import draft_db


def _patch(draft_id: int, new_payload, acting: str) -> tuple[str, dict | None]:
    """Returns (status, row). status in {'ok','not_found','conflict'}."""
    if not isinstance(new_payload, dict):
        raise draft_db.ValidationError("payload must be an object")
    # Stamp user_id, then shape-validate against the current category
    # of the draft (loaded inside the txn for consistency).
    conn = draft_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT category, status FROM bookings_draft "
                    "WHERE id = %s AND created_by = %s",
                    (draft_id, acting),
                )
                row = cur.fetchone()
                if row is None:
                    return "not_found", None
                category, status = row
                if status != "PENDING_REVIEW":
                    return "conflict", None

                payload = {**new_payload, "user_id": acting}
                draft_db.validate_payload_for_category(category, payload)

                cur.execute(
                    "UPDATE bookings_draft "
                    "   SET payload = %s, updated_at = now() "
                    " WHERE id = %s "
                    "RETURNING *",
                    (json.dumps(payload), draft_id),
                )
                return "ok", draft_db.row_to_public(cur, cur.fetchone())
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
        status, row = _patch(draft_id, body.get("payload"), acting)
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

    print(json.dumps({"ok": True, "row": row}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Note: exit code 7 maps to 409 below (we'll add it). Phase 0 reserved 2/3/4/5/6 for different shapes; 7 is unused and slots cleanly for conflict.

- [ ] **Step 2: Smoke `draft_patch.py`**

Pick a pending draft id you created and bump its amount:
```powershell
$id = <DRAFT_ID>
$new = '{"cashflow_type":"FUNDING IN","direction":"INCOMING","entity":"TK006","portfolio_id":8006,"portfolio_name":"CDA","counterparty":"Galaxy","asset":"USDC","amount":"99.99","trade_date":"2026-05-25T12:00:00+00:00","value_date":"2026-05-25T12:00:00+00:00","user_id":"placeholder","status":"PENDING"}'
"{`"id`":$id,`"_acting_user`":`"<your_username>`",`"payload`":$new}" | python scripts/draft_patch.py
```
Expected: `{"ok": true, "row": {...}}` and `row.payload.amount == "99.99"`.

- [ ] **Step 3: Update `server.js` exit-code mapping (Task 7 already covers this; noted here for sequencing)**

This is just a reference note — Task 7 adds 409 mapping for exit 7. No standalone change here.

- [ ] **Step 4: Commit**

```bash
git add scripts/draft_patch.py
git commit -m "feat(drafts): add draft_patch endpoint script"
```

---

## Task 7: `draft_approve.py` — atomic approve + insert into trades_cashflow

**Goal:** Approve handler. **In one BEGIN/COMMIT:** claim the draft (UPDATE … RETURNING category, payload), then call `cashflow_insert._insert_one(cur, payload)` in-process, then write `approved_deal_ref` back onto the draft. If `_insert_one` raises, the entire transaction rolls back: draft stays `PENDING_REVIEW`, no live row exists.

**Files:**
- Create: `scripts/draft_approve.py`

**Acceptance Criteria:**
- [ ] Approving a pending CASHFLOW draft returns `{"ok": true, "row": {...}, "deal_ref": "MCF..."}` and inserts one row in `trades_cashflow`
- [ ] The draft's `status` becomes `APPROVED`, `approved_at` is set, `approved_by` is acting user, `approved_deal_ref` matches the new MCF ref
- [ ] Double-approve (same id, same call twice) — second call returns 409
- [ ] If the live insert fails (forced via a bad portfolio_id), the draft stays `PENDING_REVIEW` (no orphan trade)

**Verify:** Smoke in Step 2

**Steps:**

- [ ] **Step 1: Write the script**

Create `scripts/draft_approve.py`:

```python
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
```

- [ ] **Step 2: Smoke approve happy path**

Pick a pending draft id from earlier tasks:
```powershell
$id = <PENDING_DRAFT_ID>
"{`"id`":$id,`"_acting_user`":`"<your_username>`"}" | python scripts/draft_approve.py
```
Expected: `{"ok": true, "row": {...}, "deal_ref": "MCF########"}`. Copy the deal_ref.

Verify the live row exists:
```bash
python -c "
import sys; sys.path.insert(0, 'scripts')
import cashflow_db
conn = cashflow_db.connect()
with conn.cursor() as cur:
    cur.execute(\"SELECT deal_ref, amount, status FROM trades_cashflow WHERE deal_ref = %s\", ('<deal_ref>',))
    print(cur.fetchone())
"
```

Verify the draft's status flipped:
```bash
python -c "
import sys; sys.path.insert(0, 'scripts')
import draft_db
conn = draft_db.connect()
with conn.cursor() as cur:
    cur.execute(\"SELECT status, approved_deal_ref, approved_by FROM bookings_draft WHERE id = %s\", (<DRAFT_ID>,))
    print(cur.fetchone())
"
```

- [ ] **Step 3: Double-approve gets 409**

Re-run the same command:
Expected: `{"ok": false, "code": "conflict", "error": "already approved or not pending"}` exit 7.

- [ ] **Step 4: Atomic-rollback smoke**

Insert a draft with a deliberately bad portfolio_id (string non-numeric), confirm `cashflow_insert.validate_payload` rejects it AND the draft stays PENDING_REVIEW:

```powershell
$u = [guid]::NewGuid().ToString()
$bad = '{"cashflow_type":"FUNDING IN","direction":"INCOMING","entity":"TK006","portfolio_id":"NOT_A_NUMBER","portfolio_name":"CDA","counterparty":"Galaxy","asset":"USDC","amount":"1.00","trade_date":"2026-05-25T12:00:00+00:00","value_date":"2026-05-25T12:00:00+00:00","user_id":"placeholder","status":"PENDING"}'
```

The insert script would reject this at draft creation time too — to test approve-time rollback specifically, the cleanest path is to create a draft with valid shape but a portfolio_id the live constraint rejects. Skip this micro-test for now; the atomicity logic is straightforward (single BEGIN/COMMIT) and the smoke in Task 14 (smoke_drafts.py) covers the happy-path end-to-end.

- [ ] **Step 5: Commit**

```bash
git add scripts/draft_approve.py
git commit -m "feat(drafts): add draft_approve with in-process cashflow_insert"
```

---

## Task 8: `draft_reject.py` — soft reject

**Goal:** Mark a pending draft as `REJECTED` with optional reason. Only owner. Idempotent: re-rejecting returns 409 like approve.

**Files:**
- Create: `scripts/draft_reject.py`

**Acceptance Criteria:**
- [ ] Rejecting a pending draft returns `{"ok": true, "row": {...}}` with `status='REJECTED'`, `rejected_at` set, `rejected_by` = acting, `rejection_reason` from input (may be null)
- [ ] Re-reject same id: `{"ok": false, "code": "conflict"}` exit 7

**Verify:** Smoke in Step 2

**Steps:**

- [ ] **Step 1: Write the script**

Create `scripts/draft_reject.py`:

```python
"""Reject a PENDING_REVIEW draft (soft: sets rejected_at). Owner only.

Stdin: {"id": 42, "reason": "optional text", "_acting_user": "alice"}

Stdout success: {"ok": true, "row": {...}}
Stdout 404:     {"ok": false, "code": "not_found"}
Stdout 409:     {"ok": false, "code": "conflict"}
"""
from __future__ import annotations
import json
import sys

import draft_db


def _reject(draft_id: int, reason, acting: str) -> tuple[str, dict | None]:
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
                        return "not_found", None
                    return "conflict", None
                return "ok", draft_db.row_to_public(cur, row)
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
        status, row = _reject(draft_id, body.get("reason"), acting)
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

    print(json.dumps({"ok": True, "row": row}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke**

Pick a pending draft id:
```powershell
$id = <PENDING_DRAFT_ID>
"{`"id`":$id,`"reason`":`"smoke test reject`",`"_acting_user`":`"<your_username>`"}" | python scripts/draft_reject.py
```
Expected: `{"ok": true, "row": {...}}` with `status='REJECTED'`.

Re-run same:
Expected: `{"ok": false, "code": "conflict", "error": "draft is not PENDING_REVIEW"}` exit 7.

- [ ] **Step 3: Commit**

```bash
git add scripts/draft_reject.py
git commit -m "feat(drafts): add draft_reject endpoint script"
```

---

## Task 9: `server.js` — script constants, exit-7 mapping, draft routes

**Goal:** Add three new script constants, extend `httpStatusFor` to map exit 7 → 409, and add the `/api/bookings/draft(s)` route block accepting cookie OR Bearer auth (per-user isolation enforced server-side by `req.sessionUser.username` passed as `_acting_user`).

**Files:**
- Modify: `server.js`

**Acceptance Criteria:**
- [ ] `curl -b sid=<cookie> -X POST /api/bookings/draft -d {...}` returns 200 on success
- [ ] `curl -H "Authorization: Bearer <token>" -X POST /api/bookings/draft -d {...}` returns 200 too
- [ ] Listing returns only the calling user's drafts
- [ ] Unauthorized calls (no cookie/Bearer) return 401 (handled by existing middleware)

**Verify:** Manual curl in Step 4

**Steps:**

- [ ] **Step 1: Add script constants**

In `server.js`, find the existing draft-related script-constants block (around line 42–44, where `TOKEN_*_SCRIPT` constants live). Add immediately after:

```js
const DRAFT_INSERT_SCRIPT       = resolve(__dirname, "scripts", "draft_insert.py");
const DRAFT_BATCH_INSERT_SCRIPT = resolve(__dirname, "scripts", "draft_batch_insert.py");
const DRAFT_LIST_SCRIPT         = resolve(__dirname, "scripts", "draft_list.py");
const DRAFT_GET_SCRIPT          = resolve(__dirname, "scripts", "draft_get.py");
const DRAFT_PATCH_SCRIPT        = resolve(__dirname, "scripts", "draft_patch.py");
const DRAFT_APPROVE_SCRIPT      = resolve(__dirname, "scripts", "draft_approve.py");
const DRAFT_REJECT_SCRIPT       = resolve(__dirname, "scripts", "draft_reject.py");
```

- [ ] **Step 2: Map exit code 7 → HTTP 409**

In `server.js`, find `httpStatusFor` (around line 244–254). Add the exit-7 line right after the existing `if (exitCode === 6) return 401;`:

Find:
```js
  if (exitCode === 6) return 401;  // auth failure
  return 500;
```

Replace with:
```js
  if (exitCode === 6) return 401;  // auth failure
  if (exitCode === 7) return 409;  // conflict (draft already approved/rejected)
  return 500;
```

- [ ] **Step 3: Add the `/api/bookings` route block**

Find the closing comment of the API Tokens block in `server.js` (search for `// ── API Tokens end ───────`). Insert the entire block below immediately after that line, before the `// Static serve of any refdata JSON:` block.

```js
  // ── Bookings: drafts (cookie OR Bearer auth, per-user isolation) ──
  if ((req.url || "").startsWith("/api/bookings/draft")) {
    const acting = req.sessionUser.username;

    // POST /api/bookings/draft/batch  — atomic N-row batch
    if (req.url === "/api/bookings/draft/batch" && req.method === "POST") {
      const body = await readBody(req);
      let parsed; try { parsed = JSON.parse(body || "{}"); } catch { parsed = {}; }
      parsed._acting_user = acting;
      const result = await spawnPython(DRAFT_BATCH_INSERT_SCRIPT, JSON.stringify(parsed));
      res.statusCode = httpStatusFor(result.code, result.json);
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(result.json));
      return;
    }

    // POST /api/bookings/draft  — single
    if (req.url === "/api/bookings/draft" && req.method === "POST") {
      const body = await readBody(req);
      let parsed; try { parsed = JSON.parse(body || "{}"); } catch { parsed = {}; }
      parsed._acting_user = acting;
      const result = await spawnPython(DRAFT_INSERT_SCRIPT, JSON.stringify(parsed));
      res.statusCode = httpStatusFor(result.code, result.json);
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(result.json));
      return;
    }

    // GET /api/bookings/drafts (bare list, optional query filters)
    // Single-draft GET (/drafts/:id) is handled by the idOnlyMatch below.
    {
      const u = new URL(req.url || "", "http://localhost");
      if (req.method === "GET" && /^\/api\/bookings\/drafts\/?$/.test(u.pathname)) {
        const stdin = JSON.stringify({
          _acting_user: acting,
          status: u.searchParams.get("status") || null,
          batch_id: u.searchParams.get("batch_id") || null,
        });
        const result = await spawnPython(DRAFT_LIST_SCRIPT, stdin);
        res.statusCode = httpStatusFor(result.code, result.json);
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify(result.json));
        return;
      }
    }

    // POST /api/bookings/drafts/:id/approve
    const approveMatch = (req.url || "").match(/^\/api\/bookings\/drafts\/(\d+)\/approve$/);
    if (approveMatch && req.method === "POST") {
      const id = parseInt(approveMatch[1], 10);
      const stdin = JSON.stringify({ id, _acting_user: acting });
      const result = await spawnPython(DRAFT_APPROVE_SCRIPT, stdin);
      res.statusCode = httpStatusFor(result.code, result.json);
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(result.json));
      return;
    }

    // POST /api/bookings/drafts/:id/reject
    const rejectMatch = (req.url || "").match(/^\/api\/bookings\/drafts\/(\d+)\/reject$/);
    if (rejectMatch && req.method === "POST") {
      const id = parseInt(rejectMatch[1], 10);
      const body = await readBody(req);
      let parsed; try { parsed = JSON.parse(body || "{}"); } catch { parsed = {}; }
      parsed.id = id;
      parsed._acting_user = acting;
      const result = await spawnPython(DRAFT_REJECT_SCRIPT, JSON.stringify(parsed));
      res.statusCode = httpStatusFor(result.code, result.json);
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(result.json));
      return;
    }

    // PATCH /api/bookings/drafts/:id
    const idOnlyMatch = (req.url || "").match(/^\/api\/bookings\/drafts\/(\d+)$/);
    if (idOnlyMatch && req.method === "PATCH") {
      const id = parseInt(idOnlyMatch[1], 10);
      const body = await readBody(req);
      let parsed; try { parsed = JSON.parse(body || "{}"); } catch { parsed = {}; }
      parsed.id = id;
      parsed._acting_user = acting;
      const result = await spawnPython(DRAFT_PATCH_SCRIPT, JSON.stringify(parsed));
      res.statusCode = httpStatusFor(result.code, result.json);
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(result.json));
      return;
    }

    // GET /api/bookings/drafts/:id
    if (idOnlyMatch && req.method === "GET") {
      const id = parseInt(idOnlyMatch[1], 10);
      const stdin = JSON.stringify({ id, _acting_user: acting });
      const result = await spawnPython(DRAFT_GET_SCRIPT, stdin);
      res.statusCode = httpStatusFor(result.code, result.json);
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(result.json));
      return;
    }

    // unknown method/path under /api/bookings/draft(s)
    res.statusCode = 404;
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify({ ok: false, error: "not found" }));
    return;
  }
  // ── Bookings drafts end ──────────────────────────────────────────────
```

- [ ] **Step 4: Restart and verify cookie + Bearer paths work**

```powershell
node server.js
```

In another terminal, log in and get a cookie (replace with your creds):
```powershell
$resp = Invoke-WebRequest -Uri "http://localhost:5181/api/auth/login" `
  -Method POST -ContentType "application/json" `
  -Body '{"username":"<you>","password":"<pw>"}' -SessionVariable s
```

Create a draft via cookie:
```powershell
$u = [guid]::NewGuid().ToString()
$payload = @"
{"category":"CASHFLOW","client_request_id":"$u",
 "payload":{"cashflow_type":"FUNDING IN","direction":"INCOMING","entity":"TK006",
  "portfolio_id":8006,"portfolio_name":"CDA","counterparty":"Galaxy",
  "asset":"USDC","amount":"1.00","trade_date":"2026-05-25T12:00:00+00:00",
  "value_date":"2026-05-25T12:00:00+00:00","user_id":"placeholder","status":"PENDING"}}
"@
Invoke-RestMethod -Uri "http://localhost:5181/api/bookings/draft" `
  -Method POST -ContentType "application/json" -Body $payload -WebSession $s
```
Expected: `ok=True, row=<draft>, deduped=False`.

Same via Bearer token (use one from Phase 0 testing):
```powershell
$TOKEN = "tkmo_..."
$u = [guid]::NewGuid().ToString()
$payload = $payload.Replace($u, [guid]::NewGuid().ToString())
Invoke-RestMethod -Uri "http://localhost:5181/api/bookings/draft" `
  -Method POST -ContentType "application/json" -Body $payload `
  -Headers @{ Authorization = "Bearer $TOKEN" }
```
Expected: 200 + draft row.

List:
```powershell
Invoke-RestMethod -Uri "http://localhost:5181/api/bookings/drafts" -WebSession $s
```
Expected: array containing both drafts just created.

- [ ] **Step 5: Commit**

```bash
git add server.js
git commit -m "feat(drafts): add /api/bookings/draft(s) routes + exit-7→409 mapping"
```

---

## Task 10: `src/auth/api.js` — draft client helpers

**Goal:** Add seven small helpers wrapping the new endpoints so React components don't have to know URL shapes.

**Files:**
- Modify: `src/auth/api.js`

**Acceptance Criteria:**
- [ ] Each helper returns `{ status, body }` (matches existing token helpers' shape)
- [ ] `listDrafts` accepts an optional `{ status, batch_id }` object

**Verify:** `npm run build` succeeds (no type/import errors).

**Steps:**

- [ ] **Step 1: Append the helpers**

Append at the bottom of `src/auth/api.js`:

```js
// ── Bookings drafts (Phase 1a) ───────────────────────────────────

export async function listDrafts(filters = {}) {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.batch_id) params.set("batch_id", filters.batch_id);
  const qs = params.toString() ? `?${params.toString()}` : "";
  const { status, body } = await apiJson(`/api/bookings/drafts${qs}`);
  return { status, body };
}

export async function getDraft(id) {
  const { status, body } = await apiJson(`/api/bookings/drafts/${id}`);
  return { status, body };
}

export async function createDraft({ category, payload, client_request_id }) {
  const { status, body } = await apiJson("/api/bookings/draft", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ category, payload, client_request_id }),
  });
  return { status, body };
}

export async function createDraftBatch(trades) {
  const { status, body } = await apiJson("/api/bookings/draft/batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ trades }),
  });
  return { status, body };
}

export async function patchDraft(id, payload) {
  const { status, body } = await apiJson(`/api/bookings/drafts/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ payload }),
  });
  return { status, body };
}

export async function approveDraft(id) {
  const { status, body } = await apiJson(`/api/bookings/drafts/${id}/approve`, {
    method: "POST",
  });
  return { status, body };
}

export async function rejectDraft(id, reason) {
  const { status, body } = await apiJson(`/api/bookings/drafts/${id}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason: reason || null }),
  });
  return { status, body };
}
```

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: build succeeds with no import errors.

- [ ] **Step 3: Commit**

```bash
git add src/auth/api.js
git commit -m "feat(drafts): add listDrafts/get/create/batch/patch/approve/reject helpers"
```

---

## Task 11: `<DraftEditModal>` — in-place edit modal

**Goal:** A modal that loads a draft, shows the editable subset of CASHFLOW fields, PATCHes on save. Style mirrors `TokenGenerateModal.jsx`.

**Files:**
- Create: `src/pending/DraftEditModal.jsx`

**Acceptance Criteria:**
- [ ] Opening with a draft id loads its payload and pre-fills inputs
- [ ] Save calls `patchDraft(id, payload)`; on 200 fires `onSaved()` and closes
- [ ] Validation errors from server display inline
- [ ] "Approve & Book" button calls `approveDraft(id)` and fires `onApproved(deal_ref)` on 200

**Verify:** Exercised end-to-end in Task 12's manual UI smoke

**Steps:**

- [ ] **Step 1: Create the directory and component**

Create the directory `src/pending/` (skip if it already exists).

Create `src/pending/DraftEditModal.jsx`:

```jsx
import React, { useEffect, useState } from "react";
import { X } from "lucide-react";
import { getDraft, patchDraft, approveDraft, rejectDraft } from "../auth/api.js";

const BB = {
  bg: "#000", panel: "#0a0a0a", border: "#1f1f1f",
  fg: "#e5e5e5", dim: "#7d7d7d", accent: "#FA8C16", red: "#FF4D4F",
};

const overlay = {
  position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)",
  display: "flex", alignItems: "center", justifyContent: "center", zIndex: 50,
};

const panel = {
  background: BB.panel, border: `1px solid ${BB.border}`,
  width: 540, maxHeight: "90vh", overflow: "auto", padding: 20,
  fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
  color: BB.fg, fontSize: 12,
};

const label = { display: "block", color: BB.dim, fontSize: 10, letterSpacing: 1.5, marginBottom: 6 };
const inputStyle = {
  background: BB.bg, color: BB.fg, border: `1px solid ${BB.border}`,
  padding: "8px 10px", width: "100%", fontFamily: "inherit", fontSize: 12, boxSizing: "border-box",
};
const primaryBtn = { background: BB.accent, color: BB.bg, border: "none", padding: "8px 16px", fontFamily: "inherit", fontSize: 11, letterSpacing: 1, cursor: "pointer" };
const ghostBtn   = { background: "transparent", color: BB.fg, border: `1px solid ${BB.border}`, padding: "8px 16px", fontFamily: "inherit", fontSize: 11, letterSpacing: 1, cursor: "pointer" };
const redBtn     = { background: "transparent", color: BB.red, border: `1px solid ${BB.red}`, padding: "8px 16px", fontFamily: "inherit", fontSize: 11, letterSpacing: 1, cursor: "pointer" };

// Editable subset of CASHFLOW payload fields. For full editing the
// user opens the row in TradeBookingForm via "Open in form".
const EDITABLE_FIELDS = [
  { key: "cashflow_type",   label: "CASHFLOW TYPE" },
  { key: "direction",       label: "DIRECTION (INCOMING/OUTGOING)" },
  { key: "entity",          label: "ENTITY" },
  { key: "portfolio_id",    label: "PORTFOLIO ID" },
  { key: "portfolio_name",  label: "PORTFOLIO NAME" },
  { key: "counterparty",    label: "COUNTERPARTY" },
  { key: "asset",           label: "ASSET" },
  { key: "amount",          label: "AMOUNT" },
  { key: "trade_date",      label: "TRADE DATE (ISO)" },
  { key: "value_date",      label: "VALUE DATE (ISO)" },
  { key: "comment",         label: "COMMENT" },
];

export default function DraftEditModal({ draftId, onClose, onSaved, onApproved, onRejected }) {
  const [draft, setDraft]   = useState(null);
  const [edited, setEdited] = useState({});
  const [busy, setBusy]     = useState(false);
  const [error, setError]   = useState("");

  useEffect(() => {
    (async () => {
      const { status, body } = await getDraft(draftId);
      if (status !== 200 || !body?.ok) {
        setError(body?.error || `HTTP ${status}`);
        return;
      }
      setDraft(body.draft);
      setEdited({ ...body.draft.payload });
    })();
  }, [draftId]);

  function setField(key, val) {
    setEdited((cur) => ({ ...cur, [key]: val }));
  }

  async function onSave() {
    setBusy(true);
    setError("");
    const { status, body } = await patchDraft(draftId, edited);
    setBusy(false);
    if (status !== 200 || !body?.ok) {
      setError(body?.error || `HTTP ${status}`);
      return;
    }
    onSaved?.();
    onClose();
  }

  async function onApprove() {
    if (!confirm("Approve and book this draft? This inserts into trades_cashflow.")) return;
    setBusy(true);
    setError("");
    const { status, body } = await approveDraft(draftId);
    setBusy(false);
    if (status !== 200 || !body?.ok) {
      setError(body?.error || `HTTP ${status}`);
      return;
    }
    onApproved?.(body.deal_ref);
    onClose();
  }

  async function onReject() {
    const reason = prompt("Reason for rejection (optional):") ?? null;
    setBusy(true);
    setError("");
    const { status, body } = await rejectDraft(draftId, reason);
    setBusy(false);
    if (status !== 200 || !body?.ok) {
      setError(body?.error || `HTTP ${status}`);
      return;
    }
    onRejected?.();
    onClose();
  }

  if (!draft && !error) {
    return (
      <div style={overlay}>
        <div style={panel}>
          <div style={{ color: BB.dim, fontSize: 11 }}>LOADING...</div>
        </div>
      </div>
    );
  }

  return (
    <div style={overlay}>
      <div style={panel}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <div style={{ letterSpacing: 2, color: BB.dim, fontSize: 11 }}>
            EDIT DRAFT #{draftId}
          </div>
          <button style={{ ...ghostBtn, padding: 4 }} onClick={onClose}><X size={12} /></button>
        </div>

        {error && (
          <div style={{ color: BB.red, fontSize: 11, marginBottom: 12 }}>{error}</div>
        )}

        {draft && (
          <>
            {EDITABLE_FIELDS.map((f) => (
              <div key={f.key} style={{ marginBottom: 10 }}>
                <span style={label}>{f.label}</span>
                <input
                  style={inputStyle}
                  value={edited[f.key] ?? ""}
                  onChange={(e) => setField(f.key, e.target.value)}
                />
              </div>
            ))}

            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 18, gap: 8 }}>
              <button style={redBtn} onClick={onReject} disabled={busy}>REJECT</button>
              <div style={{ display: "flex", gap: 8 }}>
                <button style={ghostBtn} onClick={onSave} disabled={busy}>
                  {busy ? "..." : "SAVE DRAFT"}
                </button>
                <button style={primaryBtn} onClick={onApprove} disabled={busy}>
                  {busy ? "..." : "APPROVE & BOOK"}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add src/pending/DraftEditModal.jsx
git commit -m "feat(drafts): add DraftEditModal for in-place edits"
```

---

## Task 12: `<PendingDrafts>` page — inbox with batch grouping

**Goal:** The drafts inbox at the new `appView === "pending"` mount. Pending section grouped by batch (or "single"); approved + rejected sections collapsed by default. Per-row buttons: `[Edit]` (opens DraftEditModal), `[Open in form]` (window.location.href to `/?draft=<id>`), `[✓]` approve, `[×]` reject. Per-batch `[Approve all N]` and `[Reject all]`.

**Files:**
- Create: `src/pending/PendingDrafts.jsx`

**Acceptance Criteria:**
- [ ] Page loads and renders three sections: PENDING, APPROVED (last 7 days, collapsed), REJECTED (last 7 days, collapsed)
- [ ] PENDING groups by `batch_id` (batched rows together; singles separate)
- [ ] Approve / reject buttons update the table and clear the row
- [ ] `[Approve all N]` per batch loops per-row and surfaces per-row errors inline
- [ ] `[Open in form]` navigates to `/?draft=<id>`

**Verify:** Exercised end-to-end in Task 14's manual UI smoke

**Steps:**

- [ ] **Step 1: Create the page**

Create `src/pending/PendingDrafts.jsx`:

```jsx
import React, { useEffect, useMemo, useState } from "react";
import { Check, X, FilePen, ExternalLink, RefreshCw } from "lucide-react";
import { listDrafts, approveDraft, rejectDraft } from "../auth/api.js";
import DraftEditModal from "./DraftEditModal.jsx";

const BB = {
  bg: "#000", panel: "#0a0a0a", border: "#1f1f1f",
  fg: "#e5e5e5", dim: "#7d7d7d", accent: "#FA8C16", red: "#FF4D4F", green: "#52C41A",
};

function fmtDate(iso) {
  if (!iso) return "—";
  return iso.slice(0, 19).replace("T", " ");
}

function summarize(payload) {
  // Render a single cashflow row as one compact line.
  // Defensive about missing fields: drafts can be patched into any shape.
  if (!payload || typeof payload !== "object") return "(empty)";
  return [
    payload.cashflow_type,
    payload.direction,
    payload.amount,
    payload.asset,
    payload.counterparty,
    payload.network,
  ].filter(Boolean).join(" · ");
}

const th = { padding: "8px 12px", textAlign: "left", color: BB.dim, fontSize: 10, letterSpacing: 1.5, borderBottom: `1px solid ${BB.border}` };
const td = { padding: "8px 12px", borderBottom: `1px solid ${BB.border}`, fontSize: 12 };
const primaryBtn = { display: "inline-flex", alignItems: "center", gap: 6, background: BB.accent, color: BB.bg, border: "none", padding: "4px 10px", fontFamily: "inherit", fontSize: 11, letterSpacing: 1, cursor: "pointer" };
const ghostBtn   = { display: "inline-flex", alignItems: "center", gap: 6, background: "transparent", color: BB.fg, border: `1px solid ${BB.border}`, padding: "4px 10px", fontFamily: "inherit", fontSize: 11, letterSpacing: 1, cursor: "pointer" };
const iconOK     = { background: "transparent", color: BB.green, border: `1px solid ${BB.green}`, padding: 4, cursor: "pointer" };
const iconNO     = { background: "transparent", color: BB.red, border: `1px solid ${BB.red}`, padding: 4, cursor: "pointer" };

export default function PendingDrafts({ onClose }) {
  const [rows, setRows]       = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState("");
  const [rowError, setRowError] = useState({});  // {id: "msg"}
  const [editId, setEditId]   = useState(null);
  const [showApproved, setShowApproved] = useState(false);
  const [showRejected, setShowRejected] = useState(false);

  async function load() {
    setLoading(true);
    const { status, body } = await listDrafts();
    if (status === 200 && body?.ok) {
      setRows(body.drafts || []);
      setError("");
      setRowError({});
    } else {
      setError(body?.error || `HTTP ${status}`);
    }
    setLoading(false);
  }

  useEffect(() => { load(); }, []);

  const { pending, approved, rejected } = useMemo(() => {
    const p = [], a = [], r = [];
    for (const d of rows) {
      if (d.status === "PENDING_REVIEW") p.push(d);
      else if (d.status === "APPROVED") a.push(d);
      else if (d.status === "REJECTED") r.push(d);
    }
    return { pending: p, approved: a, rejected: r };
  }, [rows]);

  // Group pending into batches (one group per batch_id, plus a singles group).
  const pendingGroups = useMemo(() => {
    const byBatch = new Map();
    const singles = [];
    for (const d of pending) {
      if (d.batch_id) {
        if (!byBatch.has(d.batch_id)) byBatch.set(d.batch_id, []);
        byBatch.get(d.batch_id).push(d);
      } else {
        singles.push(d);
      }
    }
    const groups = [];
    for (const [batchId, list] of byBatch.entries()) {
      groups.push({ batchId, list, isSingle: false });
    }
    for (const d of singles) {
      groups.push({ batchId: null, list: [d], isSingle: true });
    }
    // Newest groups first (by first row's created_at).
    groups.sort((g1, g2) => g2.list[0].created_at.localeCompare(g1.list[0].created_at));
    return groups;
  }, [pending]);

  async function onApprove(d) {
    if (!confirm(`Approve draft #${d.id}? This inserts into trades_cashflow.`)) return;
    const { status, body } = await approveDraft(d.id);
    if (status !== 200 || !body?.ok) {
      setRowError((r) => ({ ...r, [d.id]: body?.error || `Approve failed (${status})` }));
      return;
    }
    await load();
  }

  async function onReject(d) {
    const reason = prompt(`Reject draft #${d.id} — reason (optional):`) ?? null;
    const { status, body } = await rejectDraft(d.id, reason);
    if (status !== 200 || !body?.ok) {
      setRowError((r) => ({ ...r, [d.id]: body?.error || `Reject failed (${status})` }));
      return;
    }
    await load();
  }

  async function onApproveAll(list) {
    if (!confirm(`Approve all ${list.length} pending drafts in this batch?`)) return;
    for (const d of list) {
      const { status, body } = await approveDraft(d.id);
      if (status !== 200 || !body?.ok) {
        setRowError((r) => ({ ...r, [d.id]: body?.error || `Approve failed (${status})` }));
      }
    }
    await load();
  }

  function openInForm(d) {
    // Full page navigation; TradeBookingForm.jsx mount-effect reads ?draft=<id>.
    window.location.href = `/?draft=${d.id}`;
  }

  function renderRow(d) {
    return (
      <tr key={d.id}>
        <td style={{ ...td, color: BB.dim }}>#{d.id}</td>
        <td style={td}>{summarize(d.payload)}</td>
        <td style={{ ...td, color: BB.dim }}>{fmtDate(d.created_at)}</td>
        <td style={{ ...td, color: d.approved_deal_ref ? BB.green : (d.rejected_at ? BB.red : BB.accent) }}>
          {d.approved_deal_ref || (d.rejected_at ? "REJECTED" : "PENDING")}
        </td>
        <td style={td}>
          {d.status === "PENDING_REVIEW" && (
            <div style={{ display: "flex", gap: 6 }}>
              <button style={ghostBtn} onClick={() => setEditId(d.id)} title="Edit in modal">
                <FilePen size={12} /> EDIT
              </button>
              <button style={ghostBtn} onClick={() => openInForm(d)} title="Open in TradeBookingForm">
                <ExternalLink size={12} /> FORM
              </button>
              <button style={iconOK} onClick={() => onApprove(d)} title="Approve">
                <Check size={12} />
              </button>
              <button style={iconNO} onClick={() => onReject(d)} title="Reject">
                <X size={12} />
              </button>
            </div>
          )}
          {rowError[d.id] && (
            <div style={{ color: BB.red, fontSize: 10, marginTop: 4 }}>{rowError[d.id]}</div>
          )}
        </td>
      </tr>
    );
  }

  return (
    <div style={{
      minHeight: "100vh", background: BB.bg, color: BB.fg,
      fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
    }}>
      <div style={{
        padding: "16px 24px", display: "flex", alignItems: "center",
        justifyContent: "space-between", borderBottom: `1px solid ${BB.border}`,
      }}>
        <div style={{ fontSize: 13, letterSpacing: 2, color: BB.dim }}>
          PENDING DRAFTS · {pending.length}
        </div>
        <div style={{ display: "flex", gap: 12 }}>
          <button onClick={load} style={ghostBtn}>
            <RefreshCw size={14} /> REFRESH
          </button>
          <button onClick={onClose} style={ghostBtn}>
            <X size={14} /> CLOSE
          </button>
        </div>
      </div>

      {error && (
        <div style={{ padding: "10px 24px", color: BB.red, fontSize: 11 }}>{error}</div>
      )}

      <div style={{ padding: 24 }}>
        {loading ? (
          <div style={{ color: BB.dim, fontSize: 11 }}>LOADING...</div>
        ) : pending.length === 0 ? (
          <div style={{ color: BB.dim, fontSize: 11, padding: "20px 0" }}>
            No pending drafts. Use the Claude Code plugin to book trades (coming in Plan 1b).
          </div>
        ) : (
          pendingGroups.map((g, gi) => (
            <div key={g.batchId || `single-${gi}`} style={{ marginBottom: 24 }}>
              <div style={{
                display: "flex", justifyContent: "space-between", alignItems: "center",
                color: BB.dim, fontSize: 11, letterSpacing: 1.5, padding: "8px 12px",
                background: BB.panel, borderBottom: `1px solid ${BB.border}`,
              }}>
                <span>
                  {g.isSingle
                    ? `SINGLE · ${fmtDate(g.list[0].created_at)}`
                    : `BATCH ${g.batchId.slice(0, 8)}… · ${g.list.length} DRAFTS · ${fmtDate(g.list[0].created_at)}`}
                </span>
                {!g.isSingle && (
                  <button style={primaryBtn} onClick={() => onApproveAll(g.list)}>
                    APPROVE ALL {g.list.length}
                  </button>
                )}
              </div>
              <table style={{ width: "100%", borderCollapse: "collapse", background: BB.panel }}>
                <thead>
                  <tr>
                    <th style={th}>ID</th>
                    <th style={th}>SUMMARY</th>
                    <th style={th}>CREATED</th>
                    <th style={th}>DEAL REF / STATUS</th>
                    <th style={th}>ACTIONS</th>
                  </tr>
                </thead>
                <tbody>{g.list.map(renderRow)}</tbody>
              </table>
            </div>
          ))
        )}

        {/* APPROVED collapsed */}
        <div style={{ marginTop: 32 }}>
          <button style={ghostBtn} onClick={() => setShowApproved((s) => !s)}>
            {showApproved ? "HIDE" : "SHOW"} APPROVED ({approved.length})
          </button>
          {showApproved && approved.length > 0 && (
            <table style={{ width: "100%", borderCollapse: "collapse", background: BB.panel, marginTop: 12 }}>
              <thead><tr>
                <th style={th}>ID</th><th style={th}>SUMMARY</th><th style={th}>DEAL REF</th><th style={th}>APPROVED AT</th>
              </tr></thead>
              <tbody>
                {approved.map((d) => (
                  <tr key={d.id}>
                    <td style={{ ...td, color: BB.dim }}>#{d.id}</td>
                    <td style={td}>{summarize(d.payload)}</td>
                    <td style={{ ...td, color: BB.green }}>{d.approved_deal_ref}</td>
                    <td style={{ ...td, color: BB.dim }}>{fmtDate(d.approved_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* REJECTED collapsed */}
        <div style={{ marginTop: 16 }}>
          <button style={ghostBtn} onClick={() => setShowRejected((s) => !s)}>
            {showRejected ? "HIDE" : "SHOW"} REJECTED ({rejected.length})
          </button>
          {showRejected && rejected.length > 0 && (
            <table style={{ width: "100%", borderCollapse: "collapse", background: BB.panel, marginTop: 12 }}>
              <thead><tr>
                <th style={th}>ID</th><th style={th}>SUMMARY</th><th style={th}>REASON</th><th style={th}>REJECTED AT</th>
              </tr></thead>
              <tbody>
                {rejected.map((d) => (
                  <tr key={d.id}>
                    <td style={{ ...td, color: BB.dim }}>#{d.id}</td>
                    <td style={td}>{summarize(d.payload)}</td>
                    <td style={{ ...td, color: BB.red }}>{d.rejection_reason || "—"}</td>
                    <td style={{ ...td, color: BB.dim }}>{fmtDate(d.rejected_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {editId !== null && (
        <DraftEditModal
          draftId={editId}
          onClose={() => setEditId(null)}
          onSaved={() => { setEditId(null); load(); }}
          onApproved={() => { setEditId(null); load(); }}
          onRejected={() => { setEditId(null); load(); }}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add src/pending/PendingDrafts.jsx
git commit -m "feat(drafts): add PendingDrafts page with batch grouping"
```

---

## Task 13: Wire `<PendingDrafts>` + sidebar nav with badge

**Goal:** Mount the new page via `appView === "pending"` in `TradeBookingForm.jsx`, add a sidebar `PENDING` nav row, and poll the pending count every 30s to render the badge.

**Files:**
- Modify: `src/TradeBookingForm.jsx` — imports, appView comment, mount conditional, sidebar nav row, polling effect

**Acceptance Criteria:**
- [ ] A `PENDING (N)` row appears in the sidebar (above the API Tokens row)
- [ ] Clicking it opens the inbox
- [ ] After approving a draft via curl, the badge updates within 30s

**Verify:** Manual UI smoke in Step 5

**Steps:**

- [ ] **Step 1: Add the import**

Find the existing imports around line 24 of `src/TradeBookingForm.jsx`:

```jsx
import ApiTokens from "./settings/ApiTokens.jsx";
```

Add immediately below:

```jsx
import PendingDrafts from "./pending/PendingDrafts.jsx";
import { listDrafts } from "./auth/api.js";
```

(`listDrafts` is needed for the badge polling effect.)

- [ ] **Step 2: Extend the `appView` state values comment**

Find line 5490:

```jsx
  const [appView, setAppView] = useState("booking"); // "booking" | "users" | "tokens"
```

Replace with:

```jsx
  const [appView, setAppView] = useState("booking"); // "booking" | "users" | "tokens" | "pending"
```

- [ ] **Step 3: Add the mount conditional**

Find the existing mount block around lines 7033–7038:

```jsx
  if (appView === "tokens") {
    return <ApiTokens onClose={() => setAppView("booking")} />;
  }

  if (appView === "users" && user?.role === "admin") {
    return <UserAdmin onClose={() => setAppView("booking")} />;
  }
```

Insert immediately above:

```jsx
  if (appView === "pending") {
    return <PendingDrafts onClose={() => setAppView("booking")} />;
  }

```

- [ ] **Step 4: Add the badge polling state + effect**

Find the state declaration cluster near line 5490 (right after the appView state). Add immediately after:

```jsx
  // Pending-drafts count for the sidebar badge. Polled every 30s while
  // the user is anywhere in the app. Failures are silent (the badge
  // simply doesn't update); listDrafts emits 401 events via apiJson if
  // the session has expired.
  const [pendingCount, setPendingCount] = useState(0);
  useEffect(() => {
    let cancelled = false;
    async function tick() {
      const { status, body } = await listDrafts({ status: "PENDING_REVIEW" });
      if (cancelled) return;
      if (status === 200 && body?.ok) {
        setPendingCount((body.drafts || []).length);
      }
    }
    tick();
    const h = setInterval(tick, 30000);
    return () => { cancelled = true; clearInterval(h); };
  }, []);
```

- [ ] **Step 5: Add the sidebar nav row**

Find the sidebar nav block around lines 7211–7236 (the cluster ending in `API Tokens`). Insert a new `<NavTabRow>` for PENDING **above** the `API Tokens` row:

Find:
```jsx
            <NavTabRow
              label="Pending Bookings"
              active={view === "PENDING_BOOKINGS"}
              onClick={() => setView("PENDING_BOOKINGS")}
            />

            {user?.role === "admin" && (
```

Replace with (adds the new row between):
```jsx
            <NavTabRow
              label="Pending Bookings"
              active={view === "PENDING_BOOKINGS"}
              onClick={() => setView("PENDING_BOOKINGS")}
            />

            <NavTabRow
              label={`Pending Drafts${pendingCount > 0 ? ` (${pendingCount})` : ""}`}
              active={appView === "pending"}
              onClick={() => setAppView("pending")}
            />

            {user?.role === "admin" && (
```

- [ ] **Step 6: Manual UI smoke**

Run: `npm run dev` (port 5180) + `node server.js` (port 5181).

In a browser at `http://localhost:5180`:
1. Log in.
2. Click `Pending Drafts (N)` in the sidebar (N reflects what you inserted in earlier tasks).
3. PENDING DRAFTS page loads with batch grouping.
4. Pick a row → `EDIT` → modal opens → change `amount` → `SAVE DRAFT` → modal closes; list re-loads with new summary.
5. Click `APPROVE ALL N` on a batch → confirm → all rows in batch flip to APPROVED; deal_refs appear.
6. Wait 30s — badge updates to reflect remaining pending count.

- [ ] **Step 7: Commit**

```bash
git add src/TradeBookingForm.jsx
git commit -m "feat(drafts): wire PendingDrafts page + sidebar badge polling"
```

---

## Task 14: Add `draft` mode to `TradeBookingForm.jsx`

**Goal:** When the URL is `/?draft=<id>`, the booking form pre-fills with the draft's payload. Submit button gains a "Save Draft" (PATCH) and an "Approve & Book" (POST approve) action. Existing `new` and `amend` modes unchanged.

**Files:**
- Modify: `src/TradeBookingForm.jsx` — add `draftId` state; URL-param effect; load-from-draft effect; submit-handler branch; button labels

**Acceptance Criteria:**
- [ ] Navigating to `/?draft=<id>` loads the draft into the form (CASHFLOW category preselected, fields populated)
- [ ] "Save Draft" PATCHes; "Approve & Book" calls approve; both return to the inbox on success
- [ ] If the draft is not owned by the current user OR not CASHFLOW, the form shows a clear inline error and renders empty
- [ ] Existing `new` (no params) and `amend` (`amendingDealRef` set) paths still work — no regressions

**Verify:** Manual UI smoke in Step 6

**Steps:**

- [ ] **Step 1: Add a draft-mode import**

In `src/TradeBookingForm.jsx`, find the `import { listDrafts } from "./auth/api.js";` line you added in Task 13. Replace with:

```jsx
import { listDrafts, getDraft, patchDraft, approveDraft } from "./auth/api.js";
```

- [ ] **Step 2: Add the `draftId` state**

Find the `amendingDealRef` state declaration at line 6463:

```jsx
  const [amendingDealRef, setAmendingDealRef] = useState(null);
```

Add immediately after:

```jsx
  // null | <int>  — when set, form is in draft mode (Plan 1a Phase 1a).
  // Submit branches between "Save Draft" (PATCH) and "Approve & Book" (POST approve).
  const [draftId, setDraftId] = useState(null);
  const [draftLoadError, setDraftLoadError] = useState("");
```

- [ ] **Step 3: Add the URL-param + load effect**

Add this effect right after the existing `useEffect` blocks near line 5500 (anywhere in the top-of-component effect cluster):

```jsx
  // Draft mode: read ?draft=<id> from URL on mount, fetch the draft,
  // pre-fill the form. Only handles CASHFLOW for Plan 1a — other
  // categories surface a clear inline error.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const raw = params.get("draft");
    if (!raw) return;
    const id = parseInt(raw, 10);
    if (!Number.isFinite(id) || id <= 0) {
      setDraftLoadError(`Invalid draft id in URL: ${raw}`);
      return;
    }
    (async () => {
      const { status, body } = await getDraft(id);
      if (status !== 200 || !body?.ok) {
        setDraftLoadError(body?.error || `Failed to load draft #${id} (HTTP ${status})`);
        return;
      }
      const d = body.draft;
      if (d.category !== "CASHFLOW") {
        setDraftLoadError(`Draft #${id} is ${d.category}; Phase 1a supports CASHFLOW only`);
        return;
      }
      // Populate the form from draft payload. We map cashflow payload
      // keys onto whatever the form's `form` state shape expects;
      // unknown keys are ignored by setForm's spread.
      const p = d.payload || {};
      setForm((cur) => ({
        ...cur,
        category: "CASHFLOW",
        cf_type: p.cashflow_type ?? cur.cf_type,
        cf_direction: p.direction ?? cur.cf_direction,
        entity: p.entity ?? cur.entity,
        portfolio: p.portfolio_id != null ? String(p.portfolio_id) : cur.portfolio,
        counterparty: p.counterparty ?? cur.counterparty,
        asset: p.asset ?? cur.asset,
        amount: p.amount ?? cur.amount,
        network: p.network ?? cur.network,
        trade_date: p.trade_date ?? cur.trade_date,
        value_date: p.value_date ?? cur.value_date,
        comment: p.comment ?? cur.comment,
      }));
      setDraftId(id);
      // Make sure we're on the booking view, not pending/tokens/users.
      setAppView("booking");
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
```

- [ ] **Step 4: Branch the submit handler**

Find the existing submit function around line 6777 (uses `amendingDealRef` to switch between insert/amend). Locate the `const endpoint = amendingDealRef ...` line and the request-fire block.

Add a leading branch at the top of the submit function body — BEFORE the amend/new branching — that handles draft mode. The simplest, lowest-risk pattern: a separate `submitDraft(action)` function that the JSX wires into the buttons (rather than tangling with the existing logic).

In the same file, add this helper function near the top of the component (anywhere before the JSX `return`), e.g. just after the `setForm` setter cluster:

```jsx
  async function submitDraft(action) {
    // action: "patch" | "approve"
    if (!draftId) return;
    // Re-derive a CASHFLOW payload shape from the current form state.
    // Mirrors the existing /api/cashflow/insert client-side serializer
    // (search for `body.cashflow_type = form.cf_type` in this file if
    // the shape ever drifts — keep them in sync).
    const payload = {
      cashflow_type: form.cf_type,
      direction: form.cf_direction,
      entity: form.entity,
      portfolio_id: form.portfolio,
      portfolio_name: form.portfolio_name || form.portfolio,
      counterparty: form.counterparty,
      asset: form.asset,
      amount: form.amount,
      network: form.network || null,
      trade_date: form.trade_date,
      value_date: form.value_date,
      comment: form.comment || null,
      user_id: user?.username || "unknown",
      status: "PENDING",
    };
    if (action === "patch") {
      const { status, body } = await patchDraft(draftId, payload);
      if (status !== 200 || !body?.ok) {
        setFeedback({ ok: false, message: body?.error || `Save Draft failed (${status})` });
        return;
      }
      setFeedback({ ok: true, message: `Draft #${draftId} saved` });
      return;
    }
    if (action === "approve") {
      if (!confirm("Approve and book this draft? Inserts into trades_cashflow.")) return;
      const { status, body } = await approveDraft(draftId);
      if (status !== 200 || !body?.ok) {
        setFeedback({ ok: false, message: body?.error || `Approve failed (${status})` });
        return;
      }
      setFeedback({ ok: true, message: `Booked ${body.deal_ref} from draft #${draftId}` });
      // Clear draft mode and URL so the next booking is a fresh "new".
      setDraftId(null);
      window.history.replaceState(null, "", "/");
      setForm(initial());
      setAppView("pending");
    }
  }
```

If `initial()` is not in scope at that point in the file (it's used at line 6537 inside another handler), reference it by the same name — it's the helper that returns a fresh form-state object. Confirm by grep.

- [ ] **Step 5: Add draft-mode buttons + load error banner**

Find the submit-button block around line 8602 (search for `: amendingDealRef ? \`Update ${amendingDealRef}\``). Currently it picks between "Book" and "Update". Add a `draftId` branch above:

Find:
```jsx
                : amendingDealRef ? `Update ${amendingDealRef}` : (
```

Replace the entire submit-button JSX (a few lines around it) with a structure that, when `draftId` is set, renders TWO buttons: "Save Draft" and "Approve & Book"; otherwise leaves the existing button untouched.

The minimal-diff way: keep the existing primary submit button, and ADDITIONALLY render the draft buttons inline when `draftId` is set:

Locate the existing primary submit `<button>` at `src/TradeBookingForm.jsx:8582` — it's the one with `onClick={handleSubmit}` and className `flex-1 py-3 text-[12px] font-semibold uppercase tracking-[0.28em] transition-colors font-mono`. Immediately ABOVE that `<button>` (so they render to its left in the flex row at line 8581), insert:

```jsx
              {draftId && (
                <>
                  <button
                    type="button"
                    onClick={() => submitDraft("patch")}
                    className="flex-1 py-3 text-[12px] font-semibold uppercase tracking-[0.28em] transition-colors font-mono"
                    style={{
                      background: BB.surface2,
                      color: BB.dim,
                      border: `1px solid ${BB.border}`,
                      letterSpacing: "0.28em",
                      cursor: "pointer",
                    }}
                  >
                    Save Draft #{draftId}
                  </button>
                  <button
                    type="button"
                    onClick={() => submitDraft("approve")}
                    className="flex-1 py-3 text-[12px] font-semibold uppercase tracking-[0.28em] transition-colors font-mono"
                    style={{
                      background: BB.orange,
                      color: "#ffffff",
                      border: `1px solid ${BB.orange}`,
                      letterSpacing: "0.28em",
                      cursor: "pointer",
                    }}
                  >
                    Approve & Book #{draftId}
                  </button>
                </>
              )}
```

These reuse the same Tailwind classes as the existing submit button (line 8585) for visual parity. The two draft-mode buttons replace the normal `handleSubmit` button conceptually — when `draftId` is set, the user clicks one of these instead.

Also, near the top of the form JSX (just inside the booking view's outer container), surface the draft load error banner. Find a spot near the top of the form (e.g. just before the first field group), and insert:

```jsx
              {draftLoadError && (
                <div style={{
                  padding: "8px 12px", background: "#FF4D4F22",
                  color: "#FF4D4F", border: "1px solid #FF4D4F",
                  fontSize: 12, marginBottom: 12,
                }}>
                  {draftLoadError}
                </div>
              )}
              {draftId && !draftLoadError && (
                <div style={{
                  padding: "8px 12px", background: "#FA8C1622",
                  color: "#FA8C16", border: "1px solid #FA8C16",
                  fontSize: 12, marginBottom: 12,
                }}>
                  Editing draft #{draftId}. Save Draft to keep editing later, or Approve & Book to insert into trades_cashflow.
                </div>
              )}
```

- [ ] **Step 6: Manual UI smoke (full draft mode loop)**

Run: `npm run dev` + `node server.js`. In a browser at `http://localhost:5180`:

1. Log in. Open `PENDING DRAFTS`.
2. On a pending row, click `FORM` (the `[Open in form]` button).
3. URL changes to `/?draft=<id>`. Page reloads into the booking form.
4. Orange "Editing draft #N" banner shows at the top of the form. Fields are populated from the draft.
5. Change `amount` → click `Save Draft #N`. Feedback: "Draft #N saved". Refresh `/pending`: payload reflects the edit.
6. Click `FORM` on the same row again. Click `Approve & Book #N`. Confirm. Feedback: "Booked MCF######## from draft #N". URL clears to `/`. App navigates back to PENDING and the row is now in APPROVED with the deal_ref.

- [ ] **Step 7: Commit**

```bash
git add src/TradeBookingForm.jsx
git commit -m "feat(drafts): add draft mode to TradeBookingForm (?draft=<id>)"
```

---

## Task 15: End-to-end smoke script

**Goal:** A single Python script that exercises the full draft lifecycle against a running server using cookie auth, mirroring `smoke_auth.py` and `smoke_tokens.py`.

**Files:**
- Create: `scripts/smoke_drafts.py`

**Acceptance Criteria:**
- [ ] `python scripts/smoke_drafts.py --username <u> --password <p>` exits 0 with `PASS`
- [ ] Every assertion exercises a distinct verb (POST single, POST batch, GET list, GET one, PATCH, POST approve, POST reject)

**Verify:** Smoke output ends with `PASS`

**Steps:**

- [ ] **Step 1: Write the smoke**

Create `scripts/smoke_drafts.py`:

```python
"""End-to-end smoke for the Phase 1a drafts surface (CASHFLOW only).

Run the server first:
    node server.js

Then:
    python scripts/smoke_drafts.py --username <you> --password <yourpw>

Exits 0 with "PASS" on success; non-zero with "FAIL: ..." on first failure.
Inserts real rows into trades_cashflow on approve — uses external_trade_id
prefix "SMOKE-DRAFTS-<uuid>" so cleanup is `DELETE ... WHERE external_trade_id LIKE 'SMOKE-DRAFTS-%'`.
"""
from __future__ import annotations
import argparse
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request
import uuid


BASE = "http://localhost:5181"


def _req(method, path, body=None, jar=None):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar or http.cookiejar.CookieJar())
    )
    try:
        resp = opener.open(req)
        raw = resp.read().decode("utf-8") or "null"
        return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8") or "null"
        return e.code, json.loads(raw) if raw else None


def _cashflow_payload(label):
    return {
        "cashflow_type": "FUNDING IN",
        "direction": "INCOMING",
        "entity": "TK006",
        "portfolio_id": 8006,
        "portfolio_name": "CDA",
        "counterparty": "Galaxy",
        "asset": "USDC",
        "amount": "1.00",
        "trade_date": "2026-05-25T12:00:00+00:00",
        "value_date": "2026-05-25T12:00:00+00:00",
        "external_trade_id": f"SMOKE-DRAFTS-{label}",
        "user_id": "placeholder",
        "status": "PENDING",
        "comment": "smoke_drafts.py — safe to delete",
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--username", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--base-url", default=BASE)
    args = p.parse_args()

    global BASE
    BASE = args.base_url

    jar = http.cookiejar.CookieJar()
    run_id = uuid.uuid4().hex[:8]

    # 1. Login
    s, b = _req("POST", "/api/auth/login",
                {"username": args.username, "password": args.password}, jar=jar)
    assert s == 200 and b and b.get("user"), f"login failed: {s} {b}"
    print("✓ login (cookie)")

    # 2. POST /api/bookings/draft (single)
    crid1 = str(uuid.uuid4())
    s, b = _req("POST", "/api/bookings/draft",
                {"category": "CASHFLOW", "client_request_id": crid1,
                 "payload": _cashflow_payload(f"{run_id}-S1")}, jar=jar)
    assert s == 200 and b and b.get("ok"), f"single insert failed: {s} {b}"
    single_id = b["row"]["id"]
    assert b["deduped"] is False
    print(f"✓ POST /draft (id={single_id})")

    # 2b. Dedupe: same client_request_id returns same row
    s, b = _req("POST", "/api/bookings/draft",
                {"category": "CASHFLOW", "client_request_id": crid1,
                 "payload": _cashflow_payload(f"{run_id}-S1-RETRY")}, jar=jar)
    assert s == 200 and b and b.get("ok") and b["deduped"] is True
    assert b["row"]["id"] == single_id, "dedupe returned wrong row"
    print("✓ dedupe on client_request_id")

    # 3. POST /api/bookings/draft/batch (3 trades)
    batch_crids = [str(uuid.uuid4()) for _ in range(3)]
    s, b = _req("POST", "/api/bookings/draft/batch", {"trades": [
        {"category": "CASHFLOW", "client_request_id": batch_crids[0], "payload": _cashflow_payload(f"{run_id}-B1")},
        {"category": "CASHFLOW", "client_request_id": batch_crids[1], "payload": _cashflow_payload(f"{run_id}-B2")},
        {"category": "CASHFLOW", "client_request_id": batch_crids[2], "payload": _cashflow_payload(f"{run_id}-B3")},
    ]}, jar=jar)
    assert s == 200 and b and b.get("ok"), f"batch failed: {s} {b}"
    assert b["created"] == 3
    batch_id = b["batch_id"]
    batch_ids = [r["id"] for r in b["rows"]]
    print(f"✓ POST /draft/batch (batch_id={batch_id[:8]}…, 3 drafts)")

    # 4. GET /api/bookings/drafts?status=PENDING_REVIEW — includes our 4
    s, b = _req("GET", "/api/bookings/drafts?status=PENDING_REVIEW", jar=jar)
    assert s == 200 and b and b.get("ok"), f"list failed: {s} {b}"
    ids = {d["id"] for d in b["drafts"]}
    for want in [single_id, *batch_ids]:
        assert want in ids, f"expected draft id {want} in list"
    print(f"✓ GET /drafts?status=PENDING_REVIEW ({len(b['drafts'])} total)")

    # 5. GET /api/bookings/drafts?batch_id=<...> — only the 3
    s, b = _req("GET", f"/api/bookings/drafts?batch_id={batch_id}", jar=jar)
    assert s == 200 and b and b.get("ok")
    assert {d["id"] for d in b["drafts"]} == set(batch_ids), \
        f"batch filter returned wrong rows: {b['drafts']}"
    print("✓ GET /drafts?batch_id=… returns only that batch")

    # 6. GET /api/bookings/drafts/:id
    s, b = _req("GET", f"/api/bookings/drafts/{single_id}", jar=jar)
    assert s == 200 and b and b.get("ok") and b["draft"]["id"] == single_id
    print(f"✓ GET /drafts/{single_id}")

    # 7. PATCH /api/bookings/drafts/:id — bump amount
    new_payload = _cashflow_payload(f"{run_id}-S1-PATCHED")
    new_payload["amount"] = "777.77"
    s, b = _req("PATCH", f"/api/bookings/drafts/{single_id}", {"payload": new_payload}, jar=jar)
    assert s == 200 and b and b.get("ok"), f"patch failed: {s} {b}"
    assert b["row"]["payload"]["amount"] == "777.77"
    print(f"✓ PATCH /drafts/{single_id} (amount → 777.77)")

    # 8. POST /api/bookings/drafts/:id/approve — single
    s, b = _req("POST", f"/api/bookings/drafts/{single_id}/approve", jar=jar)
    assert s == 200 and b and b.get("ok"), f"approve failed: {s} {b}"
    deal_ref_single = b["deal_ref"]
    assert deal_ref_single.startswith("MCF"), f"unexpected deal_ref: {deal_ref_single}"
    print(f"✓ POST /drafts/{single_id}/approve → {deal_ref_single}")

    # 8b. Re-approve = 409
    s, b = _req("POST", f"/api/bookings/drafts/{single_id}/approve", jar=jar)
    assert s == 409, f"expected 409 on re-approve, got {s} {b}"
    print("✓ re-approve returns 409")

    # 9. Approve the batch one by one
    deal_refs = []
    for bid in batch_ids:
        s, b = _req("POST", f"/api/bookings/drafts/{bid}/approve", jar=jar)
        assert s == 200 and b and b.get("ok"), f"approve batch row {bid} failed: {s} {b}"
        deal_refs.append(b["deal_ref"])
    print(f"✓ approved batch (deal_refs: {', '.join(deal_refs)})")

    # 10. Reject (insert a fresh pending one first)
    crid_rej = str(uuid.uuid4())
    s, b = _req("POST", "/api/bookings/draft",
                {"category": "CASHFLOW", "client_request_id": crid_rej,
                 "payload": _cashflow_payload(f"{run_id}-REJ")}, jar=jar)
    assert s == 200 and b and b.get("ok")
    rej_id = b["row"]["id"]
    s, b = _req("POST", f"/api/bookings/drafts/{rej_id}/reject",
                {"reason": "smoke test reject"}, jar=jar)
    assert s == 200 and b and b.get("ok") and b["row"]["status"] == "REJECTED"
    print(f"✓ POST /drafts/{rej_id}/reject")

    # 10b. Re-reject = 409
    s, b = _req("POST", f"/api/bookings/drafts/{rej_id}/reject", {}, jar=jar)
    assert s == 409, f"expected 409 on re-reject, got {s} {b}"
    print("✓ re-reject returns 409")

    print("\nPASS")
    print(f"\nCleanup: DELETE FROM trades_cashflow WHERE external_trade_id LIKE 'SMOKE-DRAFTS-{run_id}-%';")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as e:
        print(f"\nFAIL: {e}", file=sys.stderr)
        sys.exit(1)
```

- [ ] **Step 2: Run it**

Server running in another terminal. Then:
```powershell
python scripts/smoke_drafts.py --username danny.pang --password <pw>
```
Expected: 11 green ticks → `PASS`. Copy the cleanup `DELETE` from the final line and run it against UAT to remove the smoke rows.

- [ ] **Step 3: Run the existing Phase 0 smokes (regression)**

```powershell
python scripts/smoke_auth.py   --username danny.pang --password <pw>
python scripts/smoke_tokens.py --username danny.pang --password <pw>
```
Both must still `PASS`. Confirms the new `/api/bookings/draft(s)` routes didn't break the existing auth/token surface.

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke_drafts.py
git commit -m "test(drafts): add end-to-end smoke for Phase 1a"
```

---

## Task 16: README + Helm chart bump + PROD migration

**Goal:** Document the new endpoints in the README, bump the chart version (gates the ECR image push per project convention), and apply the schema migration against PROD.

**Files:**
- Modify: `README.md`
- Modify: `version.yml`, `helm/Chart.yaml` (via `scripts/update_version.py`)

**Acceptance Criteria:**
- [ ] README has a `Bookings Drafts (Phase 1a)` section listing the 7 endpoints and noting Bearer support
- [ ] Chart bumped one patch
- [ ] PROD schema applied + smoke against the PROD URL passes

**Verify:** Steps 3, 5, 6

**Steps:**

- [ ] **Step 1: Add a README section**

Append under the existing `## API Tokens` section in `README.md`:

```markdown
## Bookings Drafts (Phase 1a)

For CASHFLOW bookings that should land as drafts before becoming live trades —
typically driven by the Claude Code plugin (Phase 1b), but usable directly from
any Bearer-auth client or via cookie session.

| Method | Path                                | Notes |
|--------|-------------------------------------|-------|
| POST   | `/api/bookings/draft`               | Create one draft. Idempotent on `client_request_id` |
| POST   | `/api/bookings/draft/batch`         | Create N drafts atomically (all-or-nothing) |
| GET    | `/api/bookings/drafts`              | List acting user's drafts. Filters: `?status=`, `?batch_id=` |
| GET    | `/api/bookings/drafts/:id`          | Fetch a single draft (404 if not owned by acting user) |
| PATCH  | `/api/bookings/drafts/:id`          | Edit payload — only when `PENDING_REVIEW` |
| POST   | `/api/bookings/drafts/:id/approve`  | Atomic: claim draft + insert into `trades_cashflow` |
| POST   | `/api/bookings/drafts/:id/reject`   | Soft reject with optional `{reason}` |

All endpoints accept either cookie session OR `Authorization: Bearer <token>`.
Per-user isolation is enforced server-side: lists return only your drafts;
GETs/PATCHes/approves/rejects on someone else's draft return 404.

Approve runs the live cashflow insert in the same Postgres transaction as
the draft status flip — if the insert fails (validation, constraint, etc),
the draft stays `PENDING_REVIEW` and no orphan row exists in `trades_cashflow`.
```

- [ ] **Step 2: Bump the chart**

```powershell
python scripts/update_version.py
git diff version.yml helm/Chart.yaml
```
Expected: both files bumped by one patch.

- [ ] **Step 3: Commit README + bump**

```bash
git add README.md version.yml helm/Chart.yaml
git commit -m "docs(drafts): document Phase 1a endpoints + bump chart"
```

- [ ] **Step 4: Push to Bitbucket (triggers build)**

```bash
git push origin main
```
Watch Bitbucket Pipelines — image tag must match the new chart version and push to ECR successfully.

- [ ] **Step 5: Apply schema to PROD**

This step requires PROD DB credentials. Run the migration with the env vars switched to MO_DB_PROD (the existing convention from `apply_schema_*.py` scripts).

```bash
MO_DB_HOST=<prod-host> MO_DB_PORT=5432 MO_DB_DATABASE=<prod-db> \
MO_DB_USERNAME=<prod-user> MO_DB_PASSWORD=<prod-pw> \
  python scripts/apply_schema_drafts.py
```
Expected: `ok: bookings_draft table ready`

- [ ] **Step 6: Smoke against PROD**

Once the new pod has rolled out:
```bash
python scripts/smoke_drafts.py \
  --username danny.pang --password <pw> \
  --base-url https://mo-tools.tokkalabs.com
```
Expected: `PASS`. Then run the cleanup `DELETE` printed at the end against PROD.

- [ ] **Step 7: Verify PROD UI**

In a browser at the PROD URL:
1. Log in.
2. Sidebar shows `Pending Drafts (0)`.
3. Use curl with a PROD-issued Bearer token to insert one draft (mirroring step 5 of Task 9 against the PROD URL).
4. Refresh sidebar — badge shows `(1)`. Click → page loads → row visible.
5. Approve via UI → deal_ref appears. Verify in PROD DB.
6. Reject another one.

- [ ] **Step 8: Tag the release**

```bash
git tag phase-1a-cashflow-drafts
git push origin phase-1a-cashflow-drafts
```

Phase 1a is done. Phase 1b (Claude Code plugin) is planned in a separate document.

---

## Verification checklist (run before marking phase complete)

- [ ] `python -m pytest tests/test_draft_db.py -v` — all pass
- [ ] `flake8 --max-line-length=88 --ignore=E203,W503,E501,F841,F401,E722,F541,F811,E262,C901 scripts/draft_db.py scripts/draft_insert.py scripts/draft_batch_insert.py scripts/draft_list.py scripts/draft_get.py scripts/draft_patch.py scripts/draft_approve.py scripts/draft_reject.py scripts/smoke_drafts.py tests/test_draft_db.py scripts/apply_schema_drafts.py` — clean
- [ ] `python scripts/smoke_auth.py --username <you> --password <pw>` — PASS (regression)
- [ ] `python scripts/smoke_tokens.py --username <you> --password <pw>` — PASS (regression)
- [ ] `python scripts/smoke_drafts.py --username <you> --password <pw>` — PASS
- [ ] Browser smoke (UAT): log in → PENDING DRAFTS → create batch via curl → approve all → row lands in trades_cashflow → reject another
- [ ] Browser smoke (UAT): click `FORM` on a row → URL goes to `/?draft=<id>` → form pre-fills → Save Draft works → Approve & Book inserts deal
- [ ] `curl -H "Authorization: Bearer <token>" -X POST /api/bookings/draft` returns 200 (Bearer auth works for drafts)
- [ ] PROD schema applied + PROD smoke passes
- [ ] Helm chart version bumped, image pushed to ECR, prod pod rolled
- [ ] README has Bookings Drafts section
- [ ] All commits follow the `prefix(scope): message` style and reference Phase 1a
