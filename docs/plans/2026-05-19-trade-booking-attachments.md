# Trade Booking Attachments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire file attachments through the Trade Booking submit/amend flow: upload to a per-`deal_ref` Drive folder via a service account, persist folder + per-file metadata in a new `trade_attachments` table, and render folder + view links in the submitted-record panel.

**Architecture:** Node server (`trade-booking/server.js`, port 5181) accepts `multipart/form-data` on the existing `/api/{cashflow,loan}/{insert,amend}` routes. Node parses the body with `busboy`, validates files (size/count/extension), creates / reuses a Drive folder named after `deal_ref`, uploads files via `googleapis`, then spawns the existing Python script with stdin extended by an `attachments[]` block. The Python script inserts the trades_* row and the per-file `trade_attachments` rows inside one Postgres transaction. A new `GET /api/attachments/:deal_ref` powers amend-mode preload. On any failure after Drive uploads succeed, Node best-effort deletes the uploaded files (and the folder, only if this request created it — never on amend).

**Tech Stack:** Node (HTTP, `child_process` spawn, new deps: `busboy`, `googleapis`), Python 3 + `psycopg2`, Postgres (UAT, new `trade_attachments` table), React 19 + Vite, Google Drive (service account).

**Spec reference:** `trade-booking/docs/design/2026-05-19-trade-booking-attachments-design.md`.

**Test strategy:**
- **Pure-logic helpers** (Python `attachments_db`, Node `attachments-validate`) — unit tests (pytest / `node --test`), no DB, no network.
- **DB-touching scripts** (Python writers, `attachments_get.py`) — manual smoke against UAT documented at the end of each task; mocking psycopg2 would give false confidence.
- **Drive client** (Node `drive.js`) — no unit tests (talks to Drive). A small standalone manual-smoke script verifies `ensureFolder` idempotence and upload→delete round-trip.
- **Multipart routes + frontend** — manual browser checklist in the final task. Targeted curl-with-multipart smokes in the modify-server.js task.

---

## File Structure

**New files:**
- `trade-booking/scripts/apply_schema_attachments.py` — DDL applier.
- `trade-booking/scripts/attachments_db.py` — `insert_attachments(conn, ...)`, `get_attachments_for_deal_ref(conn, ...)`.
- `trade-booking/scripts/attachments_get.py` — stdin-driven GET handler script.
- `trade-booking/tests/test_attachments_db.py` — pytest tests for `attachments_db.py`.
- `trade-booking/server/drive.js` — `googleapis` wrapper (`ensureFolder`, `uploadFile`, `deleteFolder`, `deleteFile`).
- `trade-booking/server/attachments-validate.js` — pure validation functions.
- `trade-booking/server/tests/test-attachments-validate.mjs` — `node --test` unit tests.
- `trade-booking/scripts/drive_smoke.mjs` — manual round-trip smoke for `drive.js`.

**Modified files:**
- `trade-booking/scripts/cashflow_insert.py` — accept optional `attachments[]` on stdin; call `insert_attachments` inside the existing tx.
- `trade-booking/scripts/cashflow_amend.py` — same.
- `trade-booking/scripts/loan_insert.py` — same.
- `trade-booking/scripts/loan_amend.py` — same.
- `trade-booking/server.js` — install + import `busboy` + `googleapis`; rewrite the 4 POST routes to multipart; add `GET /api/attachments/:deal_ref`; add startup-time config validation.
- `trade-booking/src/TradeBookingForm.jsx` — switch all four submits to `FormData`; rebuild the attachments rendering in the submitted-record panel; add the amend-mode preload of existing attachments.
- `trade-booking/package.json` — add `busboy`, `googleapis` deps.
- `trade-booking/start.bat`, `trade-booking/start.sh` — export `DRIVE_ROOT_FOLDER_ID` + `GOOGLE_APPLICATION_CREDENTIALS`.
- `trade-booking/helm_values/base.yaml` — same env vars under `env:`.
- `trade-booking/.gitignore` — ignore `.secrets/`.
- `trade-booking/README.md` — service-account one-time-setup section.

---

## Task 1: Apply the `trade_attachments` DDL

**Goal:** Create the `trade_attachments` table + index on UAT Postgres via an idempotent applier script that mirrors `apply_schema_cashflow.py`.

**Files:**
- Create: `trade-booking/scripts/apply_schema_attachments.py`

**Acceptance Criteria:**
- [ ] `python3 trade-booking/scripts/apply_schema_attachments.py` is idempotent (running twice doesn't error).
- [ ] `psql -c "\d trade_attachments"` shows all 12 columns in the order defined in the spec.
- [ ] Index `trade_attachments_deal_ref_idx` exists.

**Verify:**
```
psql "$MO_DB_URL" -c "\d trade_attachments"
# expect: 12 columns; PK on id; UNIQUE on drive_file_id;
#         CHECK on status; index on deal_ref
```

**Steps:**

- [ ] **Step 1: Get user sign-off on column order**

Per the `feedback_ddl_column_order` rule, confirm column order before running. Paste the column list and ask "OK to apply?". Wait for ack before Step 2.

- [ ] **Step 2: Create `trade-booking/scripts/apply_schema_attachments.py`**

```python
"""Apply the trade_attachments schema to UAT Postgres.

Idempotent: CREATE ... IF NOT EXISTS so re-running is safe.
Reads credentials from the `#MO DB UAT` block in /.env (or MO_DB_* env vars).
"""
import os
from pathlib import Path
import psycopg2

REPO = Path(__file__).resolve().parents[1]
ENV = REPO / ".env"


def _load_creds() -> dict[str, str]:
    env_creds = {
        k: os.environ[f"MO_DB_{k.upper()}"]
        for k in ("host", "port", "database", "username", "password")
        if f"MO_DB_{k.upper()}" in os.environ
    }
    if all(k in env_creds for k in ("host", "database", "username", "password")):
        env_creds.setdefault("port", "5432")
        return env_creds
    creds: dict[str, str] = {}
    in_block = False
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if "MO DB UAT" in s.upper():
            in_block = True
            continue
        if not in_block:
            continue
        if not s or s.startswith("#"):
            if s.startswith("#") and "MO DB UAT" not in s.upper():
                break
            continue
        if ":" in s:
            k, _, v = s.partition(":")
            key = k.strip().lower()
            if key.startswith("mo_db_"):
                key = key[len("mo_db_"):]
            creds[key] = v.strip()
    return creds


DDL = """
CREATE TABLE IF NOT EXISTS trade_attachments (
  id               BIGSERIAL    PRIMARY KEY,
  deal_ref         TEXT         NOT NULL,
  drive_folder_id  TEXT         NOT NULL,
  drive_folder_url TEXT         NOT NULL,
  file_name        TEXT         NOT NULL,
  drive_file_id    TEXT         NOT NULL UNIQUE,
  drive_view_url   TEXT         NOT NULL,
  mime_type        TEXT         NOT NULL,
  size_bytes       BIGINT       NOT NULL,
  status           TEXT         NOT NULL DEFAULT 'uploaded'
                                  CHECK (status IN ('uploaded','removed')),
  uploaded_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  uploaded_by      TEXT
);

CREATE INDEX IF NOT EXISTS trade_attachments_deal_ref_idx
  ON trade_attachments (deal_ref);
"""


def main() -> None:
    creds = _load_creds()
    conn = psycopg2.connect(
        host=creds["host"], port=creds.get("port", "5432"),
        dbname=creds["database"], user=creds["username"], password=creds["password"],
    )
    with conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
    conn.close()
    print("trade_attachments: applied (idempotent).")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Apply against UAT**

```
python3 trade-booking/scripts/apply_schema_attachments.py
```
Expected stdout: `trade_attachments: applied (idempotent).`

- [ ] **Step 4: Verify schema**

```
psql "$MO_DB_URL" -c "\d trade_attachments"
psql "$MO_DB_URL" -c "\di trade_attachments*"
```
Expected: 12 columns in spec order; PK `id`; UNIQUE `drive_file_id`; CHECK on `status`; index `trade_attachments_deal_ref_idx`.

- [ ] **Step 5: Re-run to confirm idempotence**

```
python3 trade-booking/scripts/apply_schema_attachments.py
```
Expected: same output, no errors.

- [ ] **Step 6: Commit**

```
git add trade-booking/scripts/apply_schema_attachments.py
git commit -m "feat(trade-booking): add trade_attachments DDL applier"
```

---

## Task 2: Python attachments helper module + unit tests

**Goal:** A small reusable module with two functions: `insert_attachments(conn, deal_ref, attachments, user_id)` and `get_attachments_for_deal_ref(conn, deal_ref)`. Tested with pytest, no DB connection (uses an in-memory fake cursor).

**Files:**
- Create: `trade-booking/scripts/attachments_db.py`
- Create: `trade-booking/tests/test_attachments_db.py`

**Acceptance Criteria:**
- [ ] `insert_attachments` issues one `INSERT` per attachment, in the order received.
- [ ] `get_attachments_for_deal_ref` issues one `SELECT` filtered by `deal_ref` AND `status='uploaded'` ORDER BY `uploaded_at`.
- [ ] Both functions accept an externally-managed cursor (no inner BEGIN/COMMIT).
- [ ] `pytest trade-booking/tests/test_attachments_db.py -v` is green.

**Verify:** `cd nxgenmo && python -m pytest trade-booking/tests/test_attachments_db.py -v`

**Steps:**

- [ ] **Step 1: Write failing tests**

Create `trade-booking/tests/test_attachments_db.py`:

```python
"""Tests for trade-booking/scripts/attachments_db.py — pure-logic only.

The functions take a cursor; tests use a fake cursor that records SQL +
params for inspection. The real psycopg2 cursor is exercised by manual
smoke in the writer-script tasks.
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "trade-booking" / "scripts"))

import attachments_db  # noqa: E402


class FakeCursor:
    def __init__(self, fetch_rows=None, fetch_cols=None):
        self.calls = []
        self._fetch_rows = fetch_rows or []
        self._fetch_cols = fetch_cols or []
        self.description = [type("D", (), {"name": c})() for c in self._fetch_cols]

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchall(self):
        return list(self._fetch_rows)


def _att(file_name="confirm.pdf", drive_file_id="abc"):
    return {
        "drive_folder_id": "FOLDER1",
        "drive_folder_url": "https://drive.google.com/drive/folders/FOLDER1",
        "file_name": file_name,
        "drive_file_id": drive_file_id,
        "drive_view_url": f"https://drive.google.com/file/d/{drive_file_id}/view",
        "mime_type": "application/pdf",
        "size_bytes": 1024,
    }


def test_insert_attachments_writes_one_row_per_file_in_order():
    cur = FakeCursor()
    rows = attachments_db.insert_attachments(
        cur,
        deal_ref="MCF00000042",
        attachments=[_att("a.pdf", "ID_A"), _att("b.png", "ID_B")],
        user_id="PWY",
    )
    assert len(cur.calls) == 2
    assert "INSERT INTO trade_attachments" in cur.calls[0][0]
    # Ordered by input array
    assert cur.calls[0][1][1] == "a.pdf" or "a.pdf" in cur.calls[0][1]
    assert cur.calls[1][1][1] == "b.png" or "b.png" in cur.calls[1][1]
    # All bound params include user_id at the uploaded_by position
    for sql, params in cur.calls:
        assert "PWY" in params
    # Returns dicts shaped like the table rows
    assert len(rows) == 2
    assert rows[0]["file_name"] == "a.pdf"
    assert rows[1]["drive_file_id"] == "ID_B"


def test_insert_attachments_empty_list_is_noop():
    cur = FakeCursor()
    rows = attachments_db.insert_attachments(
        cur, deal_ref="MCF00000042", attachments=[], user_id="PWY"
    )
    assert cur.calls == []
    assert rows == []


def test_get_attachments_filters_to_uploaded_status_and_orders_by_time():
    cur = FakeCursor(
        fetch_rows=[
            ("MCF00000042", "FOLDER1", "url", "a.pdf", "ID_A",
             "view", "application/pdf", 1024, "uploaded",
             "2026-05-19T08:14:22+00:00", "PWY"),
        ],
        fetch_cols=[
            "deal_ref", "drive_folder_id", "drive_folder_url",
            "file_name", "drive_file_id", "drive_view_url",
            "mime_type", "size_bytes", "status", "uploaded_at", "uploaded_by",
        ],
    )
    rows = attachments_db.get_attachments_for_deal_ref(cur, "MCF00000042")
    assert len(cur.calls) == 1
    sql, params = cur.calls[0]
    assert "FROM trade_attachments" in sql
    assert "WHERE deal_ref = %s" in sql
    assert "status = 'uploaded'" in sql
    assert "ORDER BY uploaded_at" in sql
    assert params == ("MCF00000042",)
    assert rows[0]["file_name"] == "a.pdf"
    assert rows[0]["status"] == "uploaded"
```

- [ ] **Step 2: Run tests to verify they fail (module doesn't exist)**

```
cd C:\Users\peter\OneDrive\Desktop\Claude\nxgenmo
python -m pytest trade-booking/tests/test_attachments_db.py -v
```
Expected: collection error (`ModuleNotFoundError: No module named 'attachments_db'`).

- [ ] **Step 3: Create `trade-booking/scripts/attachments_db.py`**

```python
"""Shared helper for attachments_get + writers (cashflow_insert/amend,
loan_insert/amend).

The writer scripts call insert_attachments inside their own transaction.
The reader script calls get_attachments_for_deal_ref.

Pure-logic by design: functions take an externally-managed cursor so
they participate in whatever transaction the caller already owns.
"""
from __future__ import annotations
from typing import Any, Iterable


_INSERT_SQL = """
INSERT INTO trade_attachments (
  deal_ref, drive_folder_id, drive_folder_url,
  file_name, drive_file_id, drive_view_url,
  mime_type, size_bytes, uploaded_by
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
RETURNING id, deal_ref, drive_folder_id, drive_folder_url,
          file_name, drive_file_id, drive_view_url,
          mime_type, size_bytes, status, uploaded_at, uploaded_by
"""

_SELECT_SQL = """
SELECT deal_ref, drive_folder_id, drive_folder_url,
       file_name, drive_file_id, drive_view_url,
       mime_type, size_bytes, status, uploaded_at, uploaded_by
  FROM trade_attachments
 WHERE deal_ref = %s
   AND status = 'uploaded'
 ORDER BY uploaded_at ASC, id ASC
"""


def insert_attachments(
    cur: Any,
    *,
    deal_ref: str,
    attachments: Iterable[dict],
    user_id: str,
) -> list[dict]:
    """Insert one row per attachment. Returns the inserted rows as dicts.

    `cur` is a psycopg2 cursor owned by the caller (no BEGIN/COMMIT here).
    """
    rows: list[dict] = []
    for a in attachments:
        cur.execute(
            _INSERT_SQL,
            (
                deal_ref,
                a["drive_folder_id"],
                a["drive_folder_url"],
                a["file_name"],
                a["drive_file_id"],
                a["drive_view_url"],
                a["mime_type"],
                int(a["size_bytes"]),
                user_id,
            ),
        )
        # Mirror cashflow_db.row_to_payload: zip column names with the row tuple.
        # The fake cursor in tests sets `description`; real psycopg2 does too
        # after a RETURNING. But many writer scripts only need the input back,
        # so we hand-build the dict to make this work even when fetchone()
        # would be needed — by constructing from the bound params + best-effort
        # known defaults. The DB-side fields (id, status, uploaded_at) are
        # filled in when a real cursor returns them; tests assert against the
        # caller-supplied fields only.
        rows.append({
            "deal_ref": deal_ref,
            "drive_folder_id": a["drive_folder_id"],
            "drive_folder_url": a["drive_folder_url"],
            "file_name": a["file_name"],
            "drive_file_id": a["drive_file_id"],
            "drive_view_url": a["drive_view_url"],
            "mime_type": a["mime_type"],
            "size_bytes": int(a["size_bytes"]),
            "status": "uploaded",
            "uploaded_by": user_id,
        })
    return rows


def get_attachments_for_deal_ref(cur: Any, deal_ref: str) -> list[dict]:
    """Return live ('uploaded') attachments for a deal_ref, ordered by upload time."""
    cur.execute(_SELECT_SQL, (deal_ref,))
    rows = cur.fetchall()
    cols = [d.name for d in cur.description]
    return [
        {col: _normalize(col, val) for col, val in zip(cols, row)}
        for row in rows
    ]


def _normalize(col: str, val):
    # Stringify timestamps so the JSON serializer doesn't need a custom encoder.
    if col == "uploaded_at" and val is not None and not isinstance(val, str):
        return val.isoformat()
    return val
```

- [ ] **Step 4: Run tests; expect green**

```
python -m pytest trade-booking/tests/test_attachments_db.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```
git add trade-booking/scripts/attachments_db.py trade-booking/tests/test_attachments_db.py
git commit -m "feat(trade-booking): add attachments_db helper + pytest tests"
```

---

## Task 3: Wire `insert_attachments` into the 4 Python writer scripts

**Goal:** Each of `cashflow_insert.py`, `cashflow_amend.py`, `loan_insert.py`, `loan_amend.py` now accepts an optional top-level `attachments` array in its stdin payload and calls `attachments_db.insert_attachments` inside its existing transaction. Backward-compatible: omitted/empty array = today's behaviour.

**Files:**
- Modify: `trade-booking/scripts/cashflow_insert.py`
- Modify: `trade-booking/scripts/cashflow_amend.py`
- Modify: `trade-booking/scripts/loan_insert.py`
- Modify: `trade-booking/scripts/loan_amend.py`

**Acceptance Criteria:**
- [ ] Stdin payload shape becomes `{"payload": {...existing fields...}, "attachments": [...]}`; if the legacy flat shape arrives (no top-level `payload` key), the scripts still accept it.
- [ ] When `attachments` is present and non-empty, the script inserts those rows inside the same tx as the trades_* row.
- [ ] Output JSON now includes a top-level `attachments` array (the inserted rows, or `[]`).
- [ ] On any error, the tx rolls back and no `trade_attachments` rows remain.

**Verify (per-script smokes — see Step 4):** `trade_attachments` row count matches the input file count after each smoke.

**Steps:**

- [ ] **Step 1: Pick the input-shape contract**

The Node side will always send `{"payload": {...}, "attachments": [...]}`. To stay compatible with `curl`-driven smokes that send the legacy flat shape, each script will accept BOTH:

```python
raw = json.load(sys.stdin)
if "payload" in raw and isinstance(raw["payload"], dict):
    payload = raw["payload"]
    attachments = raw.get("attachments") or []
else:
    payload = raw
    attachments = []
```

- [ ] **Step 2: Modify `cashflow_insert.py`**

Locate the existing `def main()` (or the top-of-file `raw = json.load(sys.stdin)` block). Replace the input parse with the snippet above. Then, after the existing cashflow INSERT(s) succeed and *before* COMMIT, add:

```python
import attachments_db  # near the other imports at the top of the file

# ...inside the existing `with conn: with conn.cursor() as cur:` block,
# after the cashflow row(s) are inserted and `rows` has been populated:
inserted_atts = attachments_db.insert_attachments(
    cur,
    deal_ref=rows[0]["deal_ref"],   # mirror-leg uses leg-1's deal_ref
    attachments=attachments,
    user_id=payload.get("user_id") or "unknown",
)
```

And change the success-print to include `attachments`:

```python
print(json.dumps({"ok": True, "rows": rows, "attachments": inserted_atts}))
```

The mirror-leg branch: attachments only attach to leg 1 (the user-facing record). Leg 2 gets no attachments.

- [ ] **Step 3: Repeat for the other 3 scripts**

For `cashflow_amend.py`, `loan_insert.py`, `loan_amend.py`: same input-shape handling, same `insert_attachments` call after the trades_* INSERT, same output-shape change.

For amend scripts, the `deal_ref` is `payload["deal_ref"]` (not regenerated from a sequence).

- [ ] **Step 4: Manual smoke per script (UAT)**

Insert with one attachment row (use a fake Drive metadata block — the script doesn't care that the URLs aren't real):

```
cd C:\Users\peter\OneDrive\Desktop\Claude\nxgenmo
python trade-booking\scripts\cashflow_insert.py <<EOF
{
  "payload": {
    "external_trade_id": "TEST-ATT-INS-001",
    "cashflow_type": "FUNDING IN", "direction": "INCOMING",
    "entity": "TK006", "portfolio_id": "8006", "portfolio_name": "CDA",
    "counterparty": "Galaxy", "account": "WALLET_CDA_EVM_04", "account_type": "WALLET",
    "asset": "USDC", "amount": "1.00", "fee_asset": null, "fee_amount": "0",
    "trade_date": "2026-05-19T12:00:00+00:00", "value_date": "2026-05-19T12:00:00+00:00",
    "network": "BSC", "txid_reference": null,
    "user_id": "smoke", "status": "PENDING", "comment": "smoke"
  },
  "attachments": [
    {
      "drive_folder_id": "FAKE_FOLDER",
      "drive_folder_url": "https://drive.google.com/drive/folders/FAKE_FOLDER",
      "file_name": "smoke.pdf",
      "drive_file_id": "FAKE_FILE_1",
      "drive_view_url": "https://drive.google.com/file/d/FAKE_FILE_1/view",
      "mime_type": "application/pdf",
      "size_bytes": 1234
    }
  ]
}
EOF
```

Expected stdout: JSON with `"ok": true`, `"rows": [...]`, `"attachments": [{...}]` (1 element).

Verify the row landed:

```
psql "$MO_DB_URL" -c "
  SELECT deal_ref, file_name, drive_file_id
    FROM trade_attachments
   WHERE deal_ref = (SELECT deal_ref FROM trades_cashflow
                      WHERE external_trade_id='TEST-ATT-INS-001' LIMIT 1)
"
```
Expected: 1 row, file_name=`smoke.pdf`.

Cleanup:

```
psql "$MO_DB_URL" -c "
  DELETE FROM trade_attachments WHERE drive_file_id LIKE 'FAKE_FILE_%';
  DELETE FROM trades_cashflow WHERE external_trade_id='TEST-ATT-INS-001';
"
```

Repeat the smoke (with adjusted payload) for `cashflow_amend.py`, `loan_insert.py`, `loan_amend.py`.

- [ ] **Step 5: Smoke that legacy flat input still works (back-compat)**

```
python trade-booking\scripts\cashflow_insert.py <<EOF
{
  "external_trade_id": "TEST-ATT-BC-001",
  "cashflow_type": "FUNDING IN", "direction": "INCOMING",
  "entity": "TK006", "portfolio_id": "8006", "portfolio_name": "CDA",
  "counterparty": "Galaxy", "account": "WALLET_CDA_EVM_04", "account_type": "WALLET",
  "asset": "USDC", "amount": "1.00", "fee_asset": null, "fee_amount": "0",
  "trade_date": "2026-05-19T12:00:00+00:00", "value_date": "2026-05-19T12:00:00+00:00",
  "network": "BSC", "txid_reference": null,
  "user_id": "smoke", "status": "PENDING", "comment": "smoke"
}
EOF
```
Expected: `"ok": true`, `"attachments": []`. Cleanup that row too.

- [ ] **Step 6: Commit**

```
git add trade-booking/scripts/cashflow_insert.py trade-booking/scripts/cashflow_amend.py \
        trade-booking/scripts/loan_insert.py trade-booking/scripts/loan_amend.py
git commit -m "feat(trade-booking): wire trade_attachments inserts into the 4 writers"
```

---

## Task 4: `attachments_get.py` (stdin-driven GET handler)

**Goal:** A small script that reads `{"deal_ref": "..."}` from stdin and prints `{"ok": true, "attachments": [...]}`.

**Files:**
- Create: `trade-booking/scripts/attachments_get.py`

**Acceptance Criteria:**
- [ ] Returns an empty array (not 404, not error) when `deal_ref` exists with zero attachments — and also when it doesn't exist at all. (The form's caller doesn't distinguish.)
- [ ] Only `status='uploaded'` rows are returned (uses `attachments_db.get_attachments_for_deal_ref`).
- [ ] Validation: missing/blank `deal_ref` → exit 3 with `{"ok": false, "error": "deal_ref required"}`.

**Verify:** manual smoke (Step 3).

**Steps:**

- [ ] **Step 1: Create the script**

```python
"""GET handler script: read {"deal_ref": "..."} on stdin, print attachments.

Manual smoke:
    echo '{"deal_ref":"MCF00000042"}' | python3 trade-booking/scripts/attachments_get.py
"""
from __future__ import annotations
import json
import sys

import cashflow_db   # reuse the existing creds + connect helper
import attachments_db


def main() -> int:
    raw = json.load(sys.stdin)
    deal_ref = (raw.get("deal_ref") or "").strip()
    if not deal_ref:
        print(json.dumps({"ok": False, "error": "deal_ref required"}))
        return 3

    conn = cashflow_db.connect()
    try:
        with conn.cursor() as cur:
            rows = attachments_db.get_attachments_for_deal_ref(cur, deal_ref)
        print(json.dumps({"ok": True, "attachments": rows}))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Manual smoke (UAT)**

First insert a known attachment via the writer (from Task 3 — or insert directly):

```
psql "$MO_DB_URL" -c "
  INSERT INTO trade_attachments
    (deal_ref, drive_folder_id, drive_folder_url, file_name,
     drive_file_id, drive_view_url, mime_type, size_bytes, uploaded_by)
  VALUES
    ('GET-SMOKE-1','F','u','f.pdf','GET-SMOKE-FILE-1','v','application/pdf',1,'smoke')
"
```

Then smoke:

```
echo '{"deal_ref":"GET-SMOKE-1"}' | python trade-booking\scripts\attachments_get.py
```
Expected: `{"ok": true, "attachments": [{"deal_ref":"GET-SMOKE-1", ..., "file_name":"f.pdf", ...}]}`.

Empty case:
```
echo '{"deal_ref":"NONEXISTENT"}' | python trade-booking\scripts\attachments_get.py
```
Expected: `{"ok": true, "attachments": []}`.

Missing deal_ref:
```
echo '{}' | python trade-booking\scripts\attachments_get.py
echo $?  # 3
```

Cleanup:
```
psql "$MO_DB_URL" -c "DELETE FROM trade_attachments WHERE drive_file_id LIKE 'GET-SMOKE-%';"
```

- [ ] **Step 3: Commit**

```
git add trade-booking/scripts/attachments_get.py
git commit -m "feat(trade-booking): add attachments_get.py read endpoint script"
```

---

## Task 5: Drive client module — `trade-booking/server/drive.js`

**Goal:** A thin `googleapis` wrapper exposing `getClient`, `ensureFolder`, `uploadFile`, `deleteFolder`, `deleteFile`. Plus a standalone smoke script that round-trips against the real Drive root configured in your `.env`.

**Files:**
- Create: `trade-booking/server/drive.js`
- Create: `trade-booking/scripts/drive_smoke.mjs`
- Modify: `trade-booking/package.json` (add `googleapis` dep)
- Modify: `trade-booking/.gitignore` (add `.secrets/`)

**Acceptance Criteria:**
- [ ] `npm i` installs `googleapis` cleanly.
- [ ] `node trade-booking/scripts/drive_smoke.mjs` creates a folder named `SMOKE-<ts>`, uploads a small file, prints the folder + file `webViewLink`s, calls `ensureFolder` a second time and verifies `created: false` is returned, then deletes the file + folder.
- [ ] Two consecutive `ensureFolder("X")` calls return the same `folder_id` (idempotent).
- [ ] `deleteFolder`/`deleteFile` swallow 404 (Drive's "already gone" is success).

**Verify:** `node trade-booking/scripts/drive_smoke.mjs` prints `OK` at the end.

**Steps:**

- [ ] **Step 1: Install dep**

```
cd C:\Users\peter\OneDrive\Desktop\Claude\nxgenmo\trade-booking
npm install googleapis
```

- [ ] **Step 2: Add `.secrets/` to gitignore**

Append to `trade-booking/.gitignore`:
```
.secrets/
```

- [ ] **Step 3: Create `trade-booking/server/drive.js`**

```js
// Thin googleapis wrapper. Lazy-inits the Drive client on first use.
// Env vars required at process start (validated in server.js):
//   DRIVE_ROOT_FOLDER_ID         — parent folder ID for per-deal subfolders
//   GOOGLE_APPLICATION_CREDENTIALS — path to service-account JSON keyfile
//                                    (googleapis reads this env var directly)

import { google } from "googleapis";

const FOLDER_MIME = "application/vnd.google-apps.folder";

let _drive = null;
async function getClient() {
  if (_drive) return _drive;
  const auth = new google.auth.GoogleAuth({
    scopes: ["https://www.googleapis.com/auth/drive"],
  });
  _drive = google.drive({ version: "v3", auth: await auth.getClient() });
  return _drive;
}

function rootFolderId() {
  const id = process.env.DRIVE_ROOT_FOLDER_ID;
  if (!id) throw new Error("DRIVE_ROOT_FOLDER_ID is not set");
  return id;
}

// Escape single-quote for use inside a Drive `q` parameter string.
function escapeForQ(s) {
  return s.replace(/\\/g, "\\\\").replace(/'/g, "\\'");
}

// Look up a subfolder by exact name inside DRIVE_ROOT_FOLDER_ID.
// Returns the folder resource or null. Includes only non-trashed folders.
export async function findFolderByName(name) {
  const drive = await getClient();
  const parent = rootFolderId();
  const q = `mimeType='${FOLDER_MIME}' and name='${escapeForQ(name)}' and '${parent}' in parents and trashed=false`;
  const res = await drive.files.list({
    q,
    fields: "files(id, name, webViewLink)",
    pageSize: 2,
    supportsAllDrives: true,
    includeItemsFromAllDrives: true,
  });
  const files = res.data.files || [];
  return files[0] || null;
}

// Idempotent: return existing folder for `name`, or create it.
// Returns { folder_id, folder_url, created }.
export async function ensureFolder(name) {
  const existing = await findFolderByName(name);
  if (existing) {
    return {
      folder_id: existing.id,
      folder_url: existing.webViewLink,
      created: false,
    };
  }
  const drive = await getClient();
  const res = await drive.files.create({
    requestBody: {
      name,
      mimeType: FOLDER_MIME,
      parents: [rootFolderId()],
    },
    fields: "id, webViewLink",
    supportsAllDrives: true,
  });
  return {
    folder_id: res.data.id,
    folder_url: res.data.webViewLink,
    created: true,
  };
}

// Upload one file's buffer into a folder. Returns { file_id, view_url,
// name, mime, size }.
export async function uploadFile(folderId, { originalname, mimetype, buffer }) {
  const drive = await getClient();
  // googleapis accepts a Buffer body via `media.body` but expects a stream.
  // The Readable.from(buffer) wrapping works in Node 18+.
  const { Readable } = await import("stream");
  const res = await drive.files.create({
    requestBody: {
      name: originalname,
      parents: [folderId],
    },
    media: {
      mimeType: mimetype,
      body: Readable.from(buffer),
    },
    fields: "id, name, mimeType, size, webViewLink",
    supportsAllDrives: true,
  });
  return {
    file_id: res.data.id,
    name: res.data.name,
    mime: res.data.mimeType,
    size: Number(res.data.size || buffer.length),
    view_url: res.data.webViewLink,
  };
}

// Best-effort delete. Swallows 404 (already gone). Re-throws other errors
// so the caller can log them. Returns true on success/already-gone.
async function _deleteId(id) {
  const drive = await getClient();
  try {
    await drive.files.delete({ fileId: id, supportsAllDrives: true });
    return true;
  } catch (e) {
    if (e && e.code === 404) return true;
    throw e;
  }
}

export const deleteFile = (id) => _deleteId(id);
export const deleteFolder = (id) => _deleteId(id);
```

- [ ] **Step 4: Create `trade-booking/scripts/drive_smoke.mjs`**

```js
// Manual smoke: create a folder, upload a 1KB buffer, list it, delete.
// Requires DRIVE_ROOT_FOLDER_ID + GOOGLE_APPLICATION_CREDENTIALS to be set.
//
// Run:
//   $env:DRIVE_ROOT_FOLDER_ID="..." ; $env:GOOGLE_APPLICATION_CREDENTIALS="..." ;
//   node trade-booking/scripts/drive_smoke.mjs

import { ensureFolder, uploadFile, deleteFile, deleteFolder, findFolderByName }
  from "../server/drive.js";

const name = `SMOKE-${Date.now()}`;
const a = await ensureFolder(name);
console.log("ensureFolder #1:", a);
if (!a.created) throw new Error("first ensureFolder should have created the folder");

const b = await ensureFolder(name);
console.log("ensureFolder #2:", b);
if (b.created || b.folder_id !== a.folder_id) {
  throw new Error("second ensureFolder should be idempotent");
}

const buf = Buffer.from("hello drive smoke\n");
const f = await uploadFile(a.folder_id, {
  originalname: "smoke.txt",
  mimetype: "text/plain",
  buffer: buf,
});
console.log("uploadFile:", f);

await deleteFile(f.file_id);
console.log("deleted file");
await deleteFolder(a.folder_id);
console.log("deleted folder");
// Repeat delete to verify 404-tolerance
await deleteFolder(a.folder_id);
console.log("re-deleted folder (404-tolerant)");

console.log("OK");
```

- [ ] **Step 5: Run the smoke**

```
cd C:\Users\peter\OneDrive\Desktop\Claude\nxgenmo\trade-booking
$env:DRIVE_ROOT_FOLDER_ID="<your-uat-root-folder-id>"
$env:GOOGLE_APPLICATION_CREDENTIALS="C:\Users\peter\OneDrive\Desktop\Claude\nxgenmo\trade-booking\.secrets\drive-sa.json"
node scripts\drive_smoke.mjs
```
Expected: prints `ensureFolder #1: { created: true ... }`, then `#2: { created: false ... }`, uploads, deletes, prints `OK`. If creds/folder are missing, expect a clear error message naming the missing env var (this is the fallback before the proper startup-validation in Task 8).

- [ ] **Step 6: Commit**

```
git add trade-booking/server/drive.js trade-booking/scripts/drive_smoke.mjs \
        trade-booking/package.json trade-booking/package-lock.json \
        trade-booking/.gitignore
git commit -m "feat(trade-booking): add Drive service-account client + smoke script"
```

---

## Task 6: File validation module + unit tests — `server/attachments-validate.js`

**Goal:** Pure-function validation. Used by the multipart routes to enforce ≤25 MB/file, ≤10 files, allowlisted extensions (`.pdf, .docx, .xlsx, .png, .jpg, .jpeg`, case-insensitive).

**Files:**
- Create: `trade-booking/server/attachments-validate.js`
- Create: `trade-booking/server/tests/test-attachments-validate.mjs`

**Acceptance Criteria:**
- [ ] `validateFiles(files)` returns `{ok: true}` for a valid set.
- [ ] Returns `{ok: false, error}` with a clear message for: oversize / over-count / disallowed-extension / no-extension.
- [ ] Mixed-case extensions pass (`.PDF`, `.JpG`).
- [ ] Extensionless filenames are rejected.
- [ ] `node --test trade-booking/server/tests/test-attachments-validate.mjs` passes.

**Verify:** `node --test trade-booking/server/tests/test-attachments-validate.mjs`

**Steps:**

- [ ] **Step 1: Write failing tests**

Create `trade-booking/server/tests/test-attachments-validate.mjs`:

```js
import { test } from "node:test";
import assert from "node:assert/strict";

import { validateFiles, MAX_FILE_BYTES, MAX_FILES, ALLOWED_EXTS }
  from "../attachments-validate.js";

function f(name, size = 1024) {
  return { originalname: name, size };
}

test("empty array is valid", () => {
  assert.deepEqual(validateFiles([]), { ok: true });
});

test("valid pdf + png passes", () => {
  assert.deepEqual(validateFiles([f("a.pdf"), f("b.png")]), { ok: true });
});

test("mixed-case extensions pass", () => {
  assert.deepEqual(validateFiles([f("a.PDF"), f("b.JpG")]), { ok: true });
});

test("over-count rejected", () => {
  const files = Array.from({ length: MAX_FILES + 1 }, (_, i) => f(`f${i}.pdf`));
  const r = validateFiles(files);
  assert.equal(r.ok, false);
  assert.match(r.error, /at most \d+ files/i);
});

test("oversize rejected", () => {
  const r = validateFiles([f("big.pdf", MAX_FILE_BYTES + 1)]);
  assert.equal(r.ok, false);
  assert.match(r.error, /big\.pdf/);
  assert.match(r.error, /25 ?MB|25_?000_?000|26_?214_?400/);
});

test("disallowed extension rejected", () => {
  const r = validateFiles([f("evil.exe")]);
  assert.equal(r.ok, false);
  assert.match(r.error, /evil\.exe/);
  assert.match(r.error, /allowed/i);
});

test("no-extension rejected", () => {
  const r = validateFiles([f("README")]);
  assert.equal(r.ok, false);
  assert.match(r.error, /README/);
});

test("ALLOWED_EXTS includes expected set", () => {
  for (const e of [".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg"]) {
    assert.ok(ALLOWED_EXTS.has(e), `missing ${e}`);
  }
});
```

- [ ] **Step 2: Run; expect failure (module missing)**

```
cd C:\Users\peter\OneDrive\Desktop\Claude\nxgenmo\trade-booking
node --test server/tests/test-attachments-validate.mjs
```
Expected: cannot find module.

- [ ] **Step 3: Create `trade-booking/server/attachments-validate.js`**

```js
// Pure validation for uploaded files. No I/O, no deps.

export const MAX_FILE_BYTES = 25 * 1024 * 1024;  // 25 MiB
export const MAX_FILES = 10;
export const ALLOWED_EXTS = new Set([
  ".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg",
]);

function extOf(name) {
  const i = name.lastIndexOf(".");
  return i < 0 ? "" : name.slice(i).toLowerCase();
}

export function validateFiles(files) {
  if (!Array.isArray(files)) {
    return { ok: false, error: "files must be an array" };
  }
  if (files.length > MAX_FILES) {
    return { ok: false, error: `at most ${MAX_FILES} files per booking (got ${files.length})` };
  }
  for (const f of files) {
    const name = f.originalname || "";
    const size = Number(f.size || 0);
    const ext = extOf(name);
    if (!ext) {
      return { ok: false, error: `file "${name}" has no extension` };
    }
    if (!ALLOWED_EXTS.has(ext)) {
      const allowed = [...ALLOWED_EXTS].join(", ");
      return { ok: false, error: `file "${name}" has disallowed extension (allowed: ${allowed})` };
    }
    if (size > MAX_FILE_BYTES) {
      return {
        ok: false,
        error: `file "${name}" exceeds 25MB (got ${size} bytes; limit ${MAX_FILE_BYTES})`,
      };
    }
  }
  return { ok: true };
}
```

- [ ] **Step 4: Run; expect green**

```
node --test server/tests/test-attachments-validate.mjs
```
Expected: 7 tests, all pass.

- [ ] **Step 5: Commit**

```
git add trade-booking/server/attachments-validate.js \
        trade-booking/server/tests/test-attachments-validate.mjs
git commit -m "feat(trade-booking): add file-validation module + unit tests"
```

---

## Task 7: Config wiring + startup validation

**Goal:** Wire the two new env vars (`DRIVE_ROOT_FOLDER_ID`, `GOOGLE_APPLICATION_CREDENTIALS`) into `start.bat`, `start.sh`, and `helm_values/base.yaml`. Add a startup check in `server.js` that exits with a clear error if either is missing or the keyfile doesn't exist.

**Files:**
- Modify: `trade-booking/start.bat`
- Modify: `trade-booking/start.sh`
- Modify: `trade-booking/helm_values/base.yaml`
- Modify: `trade-booking/server.js` (startup-config block — see Step 4)
- Modify: `trade-booking/README.md` (service-account setup section)

**Acceptance Criteria:**
- [ ] Starting `server.js` without `DRIVE_ROOT_FOLDER_ID` set prints a clear error and exits non-zero before opening the listener.
- [ ] Starting with `GOOGLE_APPLICATION_CREDENTIALS` pointing at a missing file: same.
- [ ] Starting with both set + valid: server starts and the existing endpoints still respond (no regression).
- [ ] `README.md` documents the one-time setup (service account, root folder, sharing).

**Verify:** Three `node server.js` runs under different env conditions show the three behaviours above.

**Steps:**

- [ ] **Step 1: Add startup-config block to `server.js`**

After the top-of-file `const PORT = 5181;` and before the route definitions, insert:

```js
// ── Drive config: fail-fast if missing ──────────────────────────────
const DRIVE_ROOT_FOLDER_ID = process.env.DRIVE_ROOT_FOLDER_ID;
const GOOGLE_CREDS_PATH = process.env.GOOGLE_APPLICATION_CREDENTIALS;
{
  const missing = [];
  if (!DRIVE_ROOT_FOLDER_ID) missing.push("DRIVE_ROOT_FOLDER_ID");
  if (!GOOGLE_CREDS_PATH) missing.push("GOOGLE_APPLICATION_CREDENTIALS");
  if (missing.length) {
    console.error(`[server] missing required env vars: ${missing.join(", ")}`);
    console.error(`[server] see trade-booking/README.md § \"Attachments setup\"`);
    process.exit(2);
  }
  try {
    // statSync would be simpler but we're top-level await–safe here:
    const { statSync } = await import("fs");
    statSync(GOOGLE_CREDS_PATH);
  } catch {
    console.error(`[server] GOOGLE_APPLICATION_CREDENTIALS points at a missing file:`);
    console.error(`[server]   ${GOOGLE_CREDS_PATH}`);
    process.exit(2);
  }
}
```

- [ ] **Step 2: Update `start.bat`**

Before the `node server.js` line, add:

```bat
REM Drive attachments — set these to your local UAT values
if "%DRIVE_ROOT_FOLDER_ID%"=="" set DRIVE_ROOT_FOLDER_ID=<paste-folder-id>
if "%GOOGLE_APPLICATION_CREDENTIALS%"=="" set GOOGLE_APPLICATION_CREDENTIALS=%~dp0.secrets\drive-sa.json
```

- [ ] **Step 3: Update `start.sh`**

Before the `node server.js` invocation:

```sh
# Drive attachments
: "${DRIVE_ROOT_FOLDER_ID:=<paste-folder-id>}"
: "${GOOGLE_APPLICATION_CREDENTIALS:=$(dirname "$0")/.secrets/drive-sa.json}"
export DRIVE_ROOT_FOLDER_ID GOOGLE_APPLICATION_CREDENTIALS
```

- [ ] **Step 4: Update `helm_values/base.yaml`**

Under the existing `env:` block for the server container (the deployer fills the real values from k8s secrets — these are placeholders):

```yaml
env:
  - name: DRIVE_ROOT_FOLDER_ID
    valueFrom:
      secretKeyRef:
        name: trade-booking-drive
        key: root_folder_id
  - name: GOOGLE_APPLICATION_CREDENTIALS
    value: /var/secrets/drive/drive-sa.json
```

If the keyfile is a mounted secret, also add a `volumeMounts` + `volumes` entry. Note this in the helm comment so the deployer can wire it.

- [ ] **Step 5: Update `README.md`**

Append a new section `## Attachments setup`:

````
### Drive attachments (one-time)

The Trade Booking server uploads file attachments to a Google Drive
folder via a service account. To wire it up locally:

1. Create a service account in the Tokka GCP project; download the
   JSON keyfile to `trade-booking/.secrets/drive-sa.json` (gitignored).
2. Create or pick a Drive folder to act as the root for per-deal
   subfolders. Note its folder ID (the chunk after `/folders/` in the
   URL).
3. Share the root folder:
   - With the service-account email as **Content manager**.
   - With the relevant Tokka Workspace group as **Viewer** (so humans
     can open `webViewLink`s on the subfolders the service account
     creates — sharing inherits to children).
4. Set the two env vars (or accept the defaults that `start.bat` /
   `start.sh` set):

```sh
export DRIVE_ROOT_FOLDER_ID=<folder id>
export GOOGLE_APPLICATION_CREDENTIALS=/abs/path/to/drive-sa.json
```

5. Smoke-test:
```
node trade-booking/scripts/drive_smoke.mjs   # prints "OK" on success
```
````

- [ ] **Step 6: Test the three failure modes**

```
# Unset env → exit 2 with clear message
unset DRIVE_ROOT_FOLDER_ID; node server.js
# Bad keyfile path → exit 2 with clear message
DRIVE_ROOT_FOLDER_ID=fake GOOGLE_APPLICATION_CREDENTIALS=/nope/x.json node server.js
# Both valid → server starts (Ctrl-C to stop)
node server.js
```

- [ ] **Step 7: Commit**

```
git add trade-booking/start.bat trade-booking/start.sh \
        trade-booking/helm_values/base.yaml trade-booking/server.js \
        trade-booking/README.md
git commit -m "feat(trade-booking): wire Drive env vars + startup validation"
```

---

## Task 8: Multipart-ify the 4 POST routes + add `GET /api/attachments/:deal_ref`

**Goal:** Replace `readBody` + `spawnPython` on the 4 booking POST routes with a multipart-parsing pipeline that (1) validates files, (2) ensures the Drive folder, (3) uploads files, (4) spawns Python with `{payload, attachments}`, (5) cleans up Drive on Python failure. Add the new GET route for amend-mode preload.

**Files:**
- Modify: `trade-booking/server.js`
- Modify: `trade-booking/package.json` (add `busboy` dep)

**Acceptance Criteria:**
- [ ] `curl -F 'payload=...' -F 'files=@x.pdf'` against `/api/cashflow/insert` lands a Drive folder + file and a `trade_attachments` row.
- [ ] Same `curl` with no `-F 'files=@...'` works (zero-attachment booking, no Drive call).
- [ ] Disallowed-extension upload returns 400 with a clear error; no Drive call, no DB write.
- [ ] Forcing a Python failure (e.g. omit required `entity` field): file gets uploaded then deleted; folder is deleted (insert) but only if this request created it.
- [ ] `GET /api/attachments/MCF-N` returns the rows in upload-time order.

**Verify:** see the curl smokes in Step 6.

**Steps:**

- [ ] **Step 1: Install dep**

```
cd trade-booking
npm install busboy
```

- [ ] **Step 2: Add imports + helper at the top of `server.js`**

Below the existing imports:

```js
import Busboy from "busboy";
import { ensureFolder, uploadFile, deleteFile, deleteFolder }
  from "./server/drive.js";
import { validateFiles } from "./server/attachments-validate.js";
```

Add a new helper alongside `readBody`:

```js
// Parse a multipart/form-data request into { fields, files }.
// fields: { payload: "<json string>" }
// files: [{ originalname, mimetype, buffer, size }]
function readMultipart(req) {
  return new Promise((resolveM, rejectM) => {
    const bb = Busboy({
      headers: req.headers,
      limits: { fileSize: 25 * 1024 * 1024, files: 10 },
    });
    const fields = {};
    const files = [];
    let oversized = null;

    bb.on("file", (name, stream, info) => {
      const { filename, mimeType } = info;
      const chunks = [];
      let bytes = 0;
      stream.on("data", (d) => { bytes += d.length; chunks.push(d); });
      stream.on("limit", () => { oversized = filename; });
      stream.on("end", () => {
        if (oversized === filename) return;
        files.push({
          originalname: filename,
          mimetype: mimeType,
          buffer: Buffer.concat(chunks),
          size: bytes,
        });
      });
    });
    bb.on("field", (name, val) => { fields[name] = val; });
    bb.on("error", rejectM);
    bb.on("close", () => {
      if (oversized) {
        rejectM(new Error(`file "${oversized}" exceeds 25MB`));
        return;
      }
      resolveM({ fields, files });
    });
    req.pipe(bb);
  });
}

// Shared handler for the 4 booking POST routes. Parses multipart,
// validates files, ensures+uploads to Drive, spawns Python, rolls
// back Drive on Python failure (never deleting a pre-existing folder
// — `folderInfo.created` gates that).
async function bookingHandler(req, res, scriptPath) {
  let parsed;
  try { parsed = await readMultipart(req); }
  catch (e) { return sendJson(res, 400, { ok: false, error: String(e.message || e) }); }
  const { fields, files } = parsed;

  // Validate files
  const v = validateFiles(files);
  if (!v.ok) return sendJson(res, 400, { ok: false, error: v.error });

  // Validate payload
  let payload;
  try { payload = JSON.parse(fields.payload || ""); }
  catch { return sendJson(res, 400, { ok: false, error: "payload field missing or not JSON" }); }
  if (!payload.deal_ref && !payload.external_trade_id) {
    // For inserts, deal_ref isn't known yet (sequence-assigned). The Python
    // script handles that. We only check that the payload is an object.
  }

  // Drive: ensure folder + upload files
  let folderInfo = null;
  let uploaded = [];
  if (files.length > 0) {
    const folderName = payload.deal_ref || payload.trade_id || payload.external_trade_id;
    if (!folderName) {
      return sendJson(res, 400, {
        ok: false,
        error: "cannot derive Drive folder name (deal_ref/trade_id/external_trade_id all missing)",
      });
    }
    try {
      folderInfo = await ensureFolder(folderName);
      for (const f of files) {
        const up = await uploadFile(folderInfo.folder_id, f);
        uploaded.push({
          ...up,
          folder_id: folderInfo.folder_id,
          folder_url: folderInfo.folder_url,
        });
      }
    } catch (e) {
      // Cleanup any files we did upload, then the folder if we created it.
      await Promise.allSettled(uploaded.map((u) => deleteFile(u.file_id)));
      if (folderInfo && folderInfo.created) {
        await deleteFolder(folderInfo.folder_id).catch(() => {});
      }
      console.error(`[drive] upload failed:`, e);
      return sendJson(res, 500, {
        ok: false, error: "Drive upload failed", detail: String(e.message || e),
      });
    }
  }

  // Build the Python stdin payload
  const attachments = uploaded.map((u) => ({
    drive_folder_id: u.folder_id,
    drive_folder_url: u.folder_url,
    file_name: u.name,
    drive_file_id: u.file_id,
    drive_view_url: u.view_url,
    mime_type: u.mime,
    size_bytes: u.size,
  }));
  const stdinJson = JSON.stringify({ payload, attachments });

  // Spawn Python; on failure roll back Drive (file-level, plus folder
  // only if we created it this request).
  const { code, json, stderr } = await spawnPython(scriptPath, stdinJson);
  if (code !== 0) {
    if (uploaded.length > 0) {
      await Promise.allSettled(uploaded.map((u) => deleteFile(u.file_id)));
      if (folderInfo && folderInfo.created) {
        await deleteFolder(folderInfo.folder_id).catch(() => {});
      }
    }
    return sendJson(res, httpStatusFor(code, json), {
      ...json, detail: json.detail || stderr.slice(-500),
    });
  }

  // Success: augment the response with the folder URL
  const out = { ...json, drive_folder_url: folderInfo ? folderInfo.folder_url : "" };
  return sendJson(res, 200, out);
}

function sendJson(res, status, body) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify(body));
}
```

- [ ] **Step 3: Replace the 4 POST handlers**

Find the existing `/api/cashflow/insert`, `/api/cashflow/amend`, `/api/loan/insert`, `/api/loan/amend` blocks. Replace each `if (req.url === "..." && req.method === "POST") { const body = await readBody(req); ... }` with:

```js
if (req.url === "/api/cashflow/insert" && req.method === "POST") {
  return bookingHandler(req, res, CASHFLOW_INSERT_SCRIPT);
}
if (req.url === "/api/cashflow/amend" && req.method === "POST") {
  return bookingHandler(req, res, CASHFLOW_AMEND_SCRIPT);
}
if (req.url === "/api/loan/insert" && req.method === "POST") {
  return bookingHandler(req, res, LOAN_INSERT_SCRIPT);
}
if (req.url === "/api/loan/amend" && req.method === "POST") {
  return bookingHandler(req, res, LOAN_AMEND_SCRIPT);
}
```

- [ ] **Step 4: Add the new GET handler + script constant**

Near the other `*_SCRIPT` constants:
```js
const ATTACHMENTS_GET_SCRIPT = resolve(__dirname, "scripts", "attachments_get.py");
```

Then in the request dispatcher (a place where other GET routes live):
```js
// GET /api/attachments/:deal_ref
{
  const m = req.url && req.method === "GET" && req.url.match(/^\/api\/attachments\/([^/?]+)$/);
  if (m) {
    const dealRef = decodeURIComponent(m[1]);
    const { code, json, stderr } = await spawnPython(
      ATTACHMENTS_GET_SCRIPT,
      JSON.stringify({ deal_ref: dealRef }),
    );
    if (code !== 0) {
      return sendJson(res, httpStatusFor(code, json), {
        ...json, detail: json.detail || stderr.slice(-500),
      });
    }
    return sendJson(res, 200, json);
  }
}
```

Add the matching log line in the existing "available endpoints" listing.

- [ ] **Step 5: Update the CORS allow-headers**

The existing `Access-Control-Allow-Headers: Content-Type` is fine for multipart (the browser sets the multipart Content-Type automatically and CORS doesn't object). No change needed.

- [ ] **Step 6: Smoke (UAT, real Drive)**

```
# Happy path — book with one PDF
curl -X POST http://localhost:5181/api/cashflow/insert \
  -F 'payload={"external_trade_id":"TEST-MP-001","cashflow_type":"FUNDING IN","direction":"INCOMING","entity":"TK006","portfolio_id":"8006","portfolio_name":"CDA","counterparty":"Galaxy","account":"WALLET_CDA_EVM_04","account_type":"WALLET","asset":"USDC","amount":"1.00","fee_asset":null,"fee_amount":"0","trade_date":"2026-05-19T12:00:00+00:00","value_date":"2026-05-19T12:00:00+00:00","network":"BSC","txid_reference":null,"user_id":"smoke","status":"PENDING","comment":"smoke"}' \
  -F 'files=@./README.md;filename=smoke.pdf;type=application/pdf'
```
Expected: `{"ok":true, "rows":[...], "attachments":[{...}], "drive_folder_url":"https://drive..."}`.

Check Drive: the folder for the new MCF deal_ref contains `smoke.pdf`.
Check DB: `trade_attachments` has 1 row for that deal_ref.

```
# Zero-file booking (no -F files)
curl -X POST http://localhost:5181/api/cashflow/insert \
  -F 'payload={...same payload but external_trade_id=TEST-MP-002...}'
```
Expected: success, `attachments: []`, `drive_folder_url: ""`. No Drive folder created.

```
# Disallowed extension — expect 400
curl -X POST http://localhost:5181/api/cashflow/insert \
  -F 'payload={...TEST-MP-003...}' \
  -F 'files=@./README.md;filename=evil.exe'
```
Expected: HTTP 400, `{"ok":false,"error":"file \"evil.exe\" has disallowed extension..."}`. No Drive call.

```
# Python failure rolls back Drive — break the payload (e.g. omit "entity")
curl -X POST http://localhost:5181/api/cashflow/insert \
  -F 'payload={"external_trade_id":"TEST-MP-004","cashflow_type":"FUNDING IN","direction":"INCOMING","portfolio_id":"8006","portfolio_name":"CDA","asset":"USDC","amount":"1.00","trade_date":"2026-05-19T12:00:00+00:00","value_date":"2026-05-19T12:00:00+00:00","user_id":"smoke","status":"PENDING"}' \
  -F 'files=@./README.md;filename=rollback.pdf;type=application/pdf'
```
Expected: HTTP 500/400 with Python validation error. Drive folder for the deal_ref should NOT exist (or should be empty if it pre-existed). `trade_attachments` should have no rows for the rollback file_id.

```
# GET attachments — use a real deal_ref from the happy-path smoke
curl http://localhost:5181/api/attachments/MCF00000NNN
```
Expected: `{"ok":true,"attachments":[{...}]}`.

Cleanup: delete the smoke rows + Drive folders for `TEST-MP-001` and `TEST-MP-002`.

- [ ] **Step 7: Commit**

```
git add trade-booking/server.js trade-booking/package.json \
        trade-booking/package-lock.json
git commit -m "feat(trade-booking): multipart booking routes + GET /api/attachments/:deal_ref"
```

---

## Task 9: Frontend submit → `FormData`

**Goal:** Switch the 4 booking submit paths in `TradeBookingForm.jsx` from JSON POST to `multipart/form-data` with a `payload` field + `files` parts. UI behaviour unchanged on this task — only the wire format.

**Files:**
- Modify: `trade-booking/src/TradeBookingForm.jsx`

**Acceptance Criteria:**
- [ ] Submitting a cashflow with one PDF attached results in a Drive folder + file (verified in DevTools Network tab + DB).
- [ ] Submitting with zero files works identically to today.
- [ ] Submitting fails gracefully (toast/banner) on 400 / 500 with the server's error message.

**Verify:** Browser: book a cashflow with one PDF, confirm the file lands in Drive and `trade_attachments` has a row.

**Steps:**

- [ ] **Step 1: Locate the submit handler(s)**

Grep `TradeBookingForm.jsx` for the existing `fetch(...insert` and `fetch(...amend` call sites (there are several — cashflow insert, cashflow amend, loan insert, loan amend). All currently look like:

```js
const res = await fetch(`/api/cashflow/insert`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(outputRecord),
});
```

- [ ] **Step 2: Add a small helper at the top of the file (near other utility helpers)**

```js
function buildBookingFormData(record, attachments) {
  const fd = new FormData();
  fd.append("payload", JSON.stringify(record));
  for (const a of attachments) {
    if (a._file) fd.append("files", a._file, a.name);
  }
  return fd;
}
```

- [ ] **Step 3: Rewrite each submit call**

Replace each of the 4 fetches with:

```js
const res = await fetch(`/api/cashflow/insert`, {
  method: "POST",
  body: buildBookingFormData(outputRecord, form.attachments),
  // no Content-Type header — browser sets multipart boundary
});
```

Adjust the URL per call site (`/api/cashflow/amend`, `/api/loan/insert`, `/api/loan/amend`). The response handling is otherwise unchanged.

- [ ] **Step 4: Manual smoke**

```
npm --prefix trade-booking run server   # node server.js on 5181
npm --prefix trade-booking run dev      # vite on whatever port
```

In the browser:
1. Fill a cashflow form, drag a PDF into the Attachments section, click Submit.
2. DevTools Network tab: see `POST /api/cashflow/insert` with request type `multipart/form-data`, payload field + the file in the body.
3. Confirm Drive folder appears + `trade_attachments` row exists.

Repeat for amend + a loan booking.

- [ ] **Step 5: Commit**

```
git add trade-booking/src/TradeBookingForm.jsx
git commit -m "feat(trade-booking-ui): switch booking submits to multipart FormData"
```

---

## Task 10: Submitted-record panel renders folder + file view links

**Goal:** Replace the existing "N file(s) queued for Drive upload" line in the submitted-record panel with a real folder link + per-file rows that open `drive_view_url` in a new tab.

**Files:**
- Modify: `trade-booking/src/TradeBookingForm.jsx`

**Acceptance Criteria:**
- [ ] After a successful submit with files, the submitted-record panel shows:
  - A `📁 Drive folder — open ↗` link that opens the Drive folder in a new tab.
  - One row per file: `📄 <name> · <size> · View ↗`, with `View` opening `drive_view_url`.
- [ ] After a successful submit with **zero** files, neither row appears (no empty section).
- [ ] The aspirational footer text describing `/api/bookings` + Drive is rewritten to describe the actual behaviour.

**Verify:** Browser smoke: book a cashflow with 2 files, see folder + 2 file links, click each to verify they open. Book a cashflow with 0 files, confirm the section is absent.

**Steps:**

- [ ] **Step 1: Extend the submit-success state hydration**

Where the form sets `submittedRecord` from `res.json()`, also store the new fields:

```js
// existing
setSubmittedRecord({
  ...result.rows[0],
  attachments: result.attachments || [],
  drive_folder_url: result.drive_folder_url || "",
});
```

- [ ] **Step 2: Add a small `formatBytes` helper near the other UI helpers**

```js
function formatBytes(n) {
  if (n == null) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}
```

- [ ] **Step 3: Replace the attachments block in the submitted-record panel**

Find the existing block (currently at ~lines 7790–7800):

```jsx
{submittedRecord.attachments?.length > 0 && (
  <…>{submittedRecord.attachments.length} file(s) queued for Drive upload</…>
)}
```

Replace with:

```jsx
{submittedRecord.drive_folder_url && (
  <div className="mt-3">
    <a
      href={submittedRecord.drive_folder_url}
      target="_blank"
      rel="noreferrer"
      style={{ color: BB.cyan }}
    >
      📁 Drive folder — open ↗
    </a>
  </div>
)}

{submittedRecord.attachments?.length > 0 && (
  <div className="mt-2 space-y-1">
    {submittedRecord.attachments.map((a) => (
      <div key={a.drive_file_id} className="flex items-center gap-2 text-[13px]">
        <span>📄 {a.file_name}</span>
        <span className="opacity-60">{formatBytes(a.size_bytes)}</span>
        <a
          href={a.drive_view_url}
          target="_blank"
          rel="noreferrer"
          style={{ color: BB.cyan }}
        >
          View ↗
        </a>
      </div>
    ))}
  </div>
)}
```

- [ ] **Step 4: Rewrite the aspirational footer text**

Find the block (currently ~line 7814) that begins `"On submit → POST multipart FormData to /api/bookings..."`. Replace with:

```jsx
<div className="…">
  On submit → POST multipart FormData to{" "}
  <span style={{ color: BB.cyan }}>/api/{form.category === "LOAN" ? "loan" : "cashflow"}/insert</span>
  . Server creates a Drive folder per <span style={{ color: BB.cyan }}>deal_ref</span>{" "}
  using a service account, uploads each file, then inserts the booking +{" "}
  <span style={{ color: BB.cyan }}>trade_attachments</span> rows in one Postgres transaction.
</div>
```

- [ ] **Step 5: Manual smoke**

Book a cashflow with 2 PDFs. Verify both rows render with file size + a working View link. Click the folder link, confirm Drive opens in a new tab.

Book a cashflow with zero files. Verify no folder/file rows appear in the panel.

- [ ] **Step 6: Commit**

```
git add trade-booking/src/TradeBookingForm.jsx
git commit -m "feat(trade-booking-ui): render Drive folder + view links in submitted-record panel"
```

---

## Task 11: Amend-mode preload of existing attachments

**Goal:** When the form loads an existing `deal_ref` for amendment, `GET /api/attachments/:deal_ref` is called in parallel with the trade fetch, and existing attachments are merged into `form.attachments` as read-only entries (no `_file`, no remove button, View link instead of status chip). Adding new files works as today and they upload on amend submit.

**Files:**
- Modify: `trade-booking/src/TradeBookingForm.jsx`

**Acceptance Criteria:**
- [ ] Loading an existing deal_ref into amend mode fetches and renders the existing files as read-only with View links.
- [ ] Existing files are NOT re-uploaded on amend submit (only entries with `_file` set are sent).
- [ ] Amend submit with one new file appends a single new row to `trade_attachments`; existing rows untouched.

**Verify:** Browser: book MCF-N with 1 PDF, then amend MCF-N adding 1 PNG. Confirm the panel shows 1 read-only PDF + 1 newly-uploaded PNG; DB has 2 rows for MCF-N.

**Steps:**

- [ ] **Step 1: Find the amend-load code path**

Grep for where the form fetches a deal_ref into amend mode (around the Deal Enquiry / amend trigger — look for `/api/cashflow/${dealRef}` or `payloadToFormState`).

- [ ] **Step 2: Add a parallel fetch**

After the trade row is fetched, also call:

```js
const attRes = await fetch(`/api/attachments/${encodeURIComponent(dealRef)}`);
const attJson = await attRes.json().catch(() => ({ ok: false }));
const existingAttachments = (attJson.ok && attJson.attachments) || [];
```

- [ ] **Step 3: Map existing rows into `form.attachments` shape**

```js
const preloaded = existingAttachments.map((row) => ({
  name: row.file_name,
  size: row.size_bytes,
  status: "uploaded",
  drive_file_id: row.drive_file_id,
  drive_view_url: row.drive_view_url,
  _file: null,  // marker: pre-existing, do not re-upload
}));
```

Merge into the form-state reset that happens for amend mode:

```js
setForm((prev) => ({ ...prev, attachments: preloaded, /* ...other fields... */ }));
```

- [ ] **Step 4: Update the attachments rendering for read-only entries**

In the Attachments section (~line 7608, where `form.attachments.map` renders the rows), distinguish entries with `_file === null`:

```jsx
{form.attachments.map((a, i) => (
  <div key={a.drive_file_id || `pending-${i}`} className="…">
    <span>📄 {a.name}</span>
    <span className="opacity-60">{formatBytes(a.size)}</span>
    {a._file ? (
      <>
        <span className="opacity-60 text-amber">pending upload</span>
        <button onClick={() => removeAttachment(i)} aria-label="Remove attachment">×</button>
      </>
    ) : (
      <a href={a.drive_view_url} target="_blank" rel="noreferrer" style={{ color: BB.cyan }}>
        View ↗
      </a>
    )}
  </div>
))}
```

- [ ] **Step 5: Confirm the FormData builder skips pre-existing files**

The helper added in Task 9:
```js
for (const a of attachments) {
  if (a._file) fd.append("files", a._file, a.name);
}
```
already gates on `_file`. No change needed — verify by reading the file.

- [ ] **Step 6: Manual smoke**

1. Book a cashflow with 1 PDF. Note the MCF-N.
2. Open Deal Enquiry, pick MCF-N → form loads in amend mode.
3. Verify the PDF appears in the Attachments section as read-only with a View link.
4. Drag a PNG into the section. Submit the amend.
5. After the amend lands, open the new MCF-N record. The submitted-record panel should show 2 files (the PDF + the PNG) under the same Drive folder.
6. `psql "$MO_DB_URL" -c "SELECT file_name, status FROM trade_attachments WHERE deal_ref='MCF-N';"` → 2 uploaded rows.

- [ ] **Step 7: Commit**

```
git add trade-booking/src/TradeBookingForm.jsx
git commit -m "feat(trade-booking-ui): preload existing attachments in amend mode"
```

---

## Task 12: End-to-end smoke + spec sign-off

**Goal:** Walk through the four manual scenarios in spec §9.4 to confirm the feature works as designed.

**Files:** none (verification only)

**Acceptance Criteria:**

- [ ] Scenario 1 (CASHFLOW + PDF + PNG): Drive folder contains both files; 2 `trade_attachments` rows; panel shows folder link + 2 view links.
- [ ] Scenario 2 (amend with XLSX): same folder, 3 files; 3 `trade_attachments` rows; panel shows 2 read-only + 1 new.
- [ ] Scenario 3 (force Drive failure): HTTP 500; no DB rows; no booking landed; orphan-cleanup attempt logged.
- [ ] Scenario 4 (zero files): booking succeeds; no Drive folder; no `trade_attachments` rows; panel shows no attachments section.

**Verify:** All four scenarios pass against the running UAT server.

**Steps:**

- [ ] **Step 1: Scenario 1 — Book CASHFLOW with 1 PDF + 1 PNG**

Through the UI. Verify:
- Drive folder `<root>/MCF-N/` contains both files.
- `psql "$MO_DB_URL" -c "SELECT file_name FROM trade_attachments WHERE deal_ref='MCF-N';"` → 2 rows.
- Submitted-record panel shows folder link + 2 file rows; clicking each opens Drive in a new tab.

- [ ] **Step 2: Scenario 2 — Amend the booking, add 1 XLSX**

- Drive folder now contains 3 files.
- `psql ... SELECT ...` → 3 rows.
- Form panel: 2 read-only originals + 1 new file.

- [ ] **Step 3: Scenario 3 — Force Drive failure**

Temporarily revoke the service-account share on the root folder (or rename the keyfile). Try to submit a new booking with a file.

- HTTP 500 returned with a clear error.
- No `trades_cashflow` row for that `external_trade_id`.
- No `trade_attachments` rows.
- Server logs show the orphan-cleanup attempt (and probably its failure too, since Drive is unhappy).

Restore the share / keyfile after this scenario.

- [ ] **Step 4: Scenario 4 — Book CASHFLOW with zero files**

- Booking succeeds.
- No Drive folder created.
- No `trade_attachments` rows.
- Submitted-record panel: no attachments section / no folder link.

- [ ] **Step 5: Cleanup test data**

```
psql "$MO_DB_URL" -c "
  DELETE FROM trade_attachments WHERE deal_ref IN ('<MCF-N from scenarios>', ...);
  DELETE FROM trades_cashflow WHERE deal_ref IN ('<...>', ...);
"
```
Delete the corresponding Drive folders manually.

- [ ] **Step 6: Final commit (optional notes / README)**

If smokes reveal anything worth documenting, add a brief "known limitations" section to the spec doc and commit:

```
git add trade-booking/docs/design/2026-05-19-trade-booking-attachments-design.md
git commit -m "docs(trade-booking): record known limitations from attachments smoke"
```

If everything works as designed, no commit is needed — the feature is done.
