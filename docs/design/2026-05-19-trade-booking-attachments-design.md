# Trade Booking Attachments — Design

**Date:** 2026-05-19
**Module:** `trade-booking/`
**Status:** Draft for review

## 1. Purpose

The Trade Booking form has an "Attachments" section in the UI (drag-and-drop
file input, line ~7550 of `src/TradeBookingForm.jsx`) but on submit the
file bytes are stripped (`form.attachments.map(({ _file, ...rest }) => rest)`)
and the server stores only filename/size metadata. There is no Drive
upload, no folder link, no way for anyone to retrieve the document.

This spec adds the missing back half: a multipart submit path that
uploads files to a Drive folder per `deal_ref` via a service account,
persists folder + per-file metadata in a new `trade_attachments` table,
and surfaces folder + view links in the submitted-record panel for both
fresh-submit and amend flows.

## 2. Scope

**In scope (v1):**

- CASHFLOW and LOAN booking endpoints (the two whose backends exist
  per `2026-05-15-cashflow-booking-backend-design.md`).
- Fresh insert: create a Drive folder named after `deal_ref`, upload
  files, insert one `trade_attachments` row per file inside the same
  Postgres transaction as the booking row.
- Amend: append-only — new files land in the same folder; pre-existing
  files are immutable. UI shows existing files read-only with view
  links, allows adding more.
- `GET /api/attachments/:deal_ref` for the amend-mode preload.
- View access via Drive `webViewLink` (Tokka Workspace login required;
  folder shared with org group at the root level so subfolders inherit).

**Out of scope (v1, deferred):**

- SPOT / FUTURE attachments — their booking endpoints don't exist yet.
  The same pattern can be replicated when those backends are built.
- Soft-delete UI (`status='removed'`). The column exists in the DDL
  but no UI lets a user remove a file in v1.
- Download proxying. v1 only offers Drive `webViewLink` (opens in new
  tab — Drive handles preview / download from there).
- Attachment listing outside the form (e.g. in `dashboard/` or in the
  `/api/cashflow/recent` response).
- Authentication. `uploaded_by` comes from the form's "Created by"
  dropdown, same trust model as the existing `user_id`.
- Virus scanning, OCR, content extraction.

## 3. Architecture

Mirrors the existing pattern (`server.js` Node routes spawn small
Python scripts that talk to Postgres). One new piece: a Drive client
lives in **Node**, not Python, because file bytes flow through Node
once and re-marshaling buffers across the Node→Python pipe would be
wasteful.

### 3.1 Endpoints (added to / modified in `trade-booking/server.js`, port 5181)

| Method | Route | Change | Spawns |
| ------ | ----- | ------ | ------ |
| POST | `/api/cashflow/insert` | Accept `multipart/form-data` instead of JSON | `scripts/cashflow_insert.py` |
| POST | `/api/cashflow/amend`  | Accept `multipart/form-data` instead of JSON | `scripts/cashflow_amend.py`  |
| POST | `/api/loan/insert`     | Accept `multipart/form-data` instead of JSON | `scripts/loan_insert.py`     |
| POST | `/api/loan/amend`      | Accept `multipart/form-data` instead of JSON | `scripts/loan_amend.py`      |
| GET  | `/api/attachments/:deal_ref` | **New** — list current attachments for a deal_ref | `scripts/attachments_get.py` |

The four POST endpoints are backward-compatible from the Python side:
the existing scripts already accept a JSON payload on stdin and produce
the existing response shape; the only addition is an optional
`attachments` field on stdin (see §5.2).

### 3.2 Multipart body shape

The frontend sends `multipart/form-data` with two field types:

- `payload` — a single form field whose value is a JSON-encoded string
  matching the exact shape the existing endpoints accept today
  (`outputRecord` / `loanRecord`).
- `files` — zero or more file parts (`files[]`).

Multer parses with memory storage and these limits:

```js
multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 25 * 1024 * 1024, files: 10 },
})
```

Files larger than 25 MB or counts over 10 trip multer's built-in error
handling; the route's error handler converts those to HTTP 400 with a
`{"ok": false, "error": "..."}` envelope before any Drive call.

### 3.3 Per-request flow (POST /api/cashflow/insert example)

```
TradeBookingForm.handleSubmit()
  build FormData:
    payload = JSON.stringify(outputRecord)
    files[] = each form.attachments[i]._file
  POST /api/cashflow/insert  (Content-Type: multipart/form-data — browser sets boundary)

server.js handler:
  multer parses body                                        → req.body.payload, req.files
  validateFiles(req.files)                                  → 400 on violation
  JSON.parse(req.body.payload)                              → payload
  drive.ensureFolder(payload.deal_ref)                      → { folder_id, folder_url, created }
  for each file:
    drive.uploadFile(folder_id, file)                       → { file_id, view_url, size, mime }
  spawn cashflow_insert.py, stdin = { payload, attachments }
    Python:
      BEGIN
      INSERT INTO trades_cashflow (...) RETURNING *
      INSERT INTO trade_attachments (...) per file
      COMMIT
      print {"ok": true, "rows": [...], "attachments": [...]}
    on non-zero exit:
      drive cleanup (see §6)
      forward Python stderr as 500
  forward Python stdout as 200, augmented with folder_url already in attachments rows
```

### 3.4 Drive folder layout

```
<DRIVE_ROOT_FOLDER_ID>/
  MCF-42/                        ← created on first booking of deal_ref MCF-42
    confirm.pdf
    statement.xlsx
  MLN-17/                        ← loan booking
    term-sheet.pdf
```

`ensureFolder(deal_ref)` is idempotent — looks up `<root>/<deal_ref>` by
exact name match and creates only if absent. This is what makes amend
(re-upload to the same `deal_ref`) land in the same folder.

Sharing: the root folder is shared once, manually, with the service
account email (Content manager) and a Tokka Workspace group (Viewer).
Subfolders inherit, so humans can open `webViewLink`s without per-folder
sharing logic in the code.

### 3.5 Component layout

```
trade-booking/
  server.js                              ← modified: multipart routes, new attachments route
  server/                                ← new directory
    drive.js                             ← googleapis wrapper
    attachments-validate.js              ← pure file-validation functions
  src/
    TradeBookingForm.jsx                 ← modified: FormData submit, panel rendering, amend preload
  scripts/
    apply_schema_attachments.py          ← new: DDL applier
    attachments_db.py                    ← new: insert/read helpers
    attachments_get.py                   ← new: read-back for GET endpoint
    cashflow_insert.py                   ← modified: optional attachments[] in payload
    cashflow_amend.py                    ← modified: same
    loan_insert.py                       ← modified: same
    loan_amend.py                        ← modified: same
  tests/
    test_attachments_db.py               ← new
    server/
      test-drive.js                      ← new (mocks googleapis)
      test-attachments-validate.js       ← new
```

## 4. DDL — `trade_attachments`

Lives on UAT Postgres `middle_office`. Not bitemporal — folder is per
`deal_ref`, history is via append-only rows + a soft-delete column
reserved for future UI.

Column order (subject to user approval per `feedback_ddl_column_order`
memory — confirm before applying):

```sql
CREATE TABLE trade_attachments (
  id               BIGSERIAL PRIMARY KEY,
  deal_ref         TEXT        NOT NULL,
  drive_folder_id  TEXT        NOT NULL,
  drive_folder_url TEXT        NOT NULL,
  file_name        TEXT        NOT NULL,
  drive_file_id    TEXT        NOT NULL UNIQUE,
  drive_view_url   TEXT        NOT NULL,
  mime_type        TEXT        NOT NULL,
  size_bytes       BIGINT      NOT NULL,
  status           TEXT        NOT NULL DEFAULT 'uploaded'
                                CHECK (status IN ('uploaded','removed')),
  uploaded_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  uploaded_by      TEXT
);

CREATE INDEX trade_attachments_deal_ref_idx ON trade_attachments(deal_ref);
```

Notes:

- `drive_file_id` is globally unique within a Drive (the `UNIQUE`
  constraint is a defensive belt-and-braces — Drive's own IDs are
  already unique, so a collision means we accidentally double-inserted).
- `deal_ref` is not a foreign key to `trades_cashflow.deal_ref` (or any
  other trades_* table) — attachments are intentionally
  category-agnostic so the same table serves CASHFLOW, LOAN, and any
  later category without a JOIN dance.
- No `effective_start` / `effective_end` columns. The trades_* tables
  are bitemporal; this one is not, by design. The folder + files
  outlive any individual amend snapshot.

Applied via `scripts/apply_schema_attachments.py`, identical structure
to `apply_schema_cashflow.py` (reads `#MO DB UAT` from `.env`, idempotent
`CREATE TABLE IF NOT EXISTS`, idempotent `CREATE INDEX IF NOT EXISTS`).

## 5. API contract

### 5.1 Common envelope

Same as the existing booking endpoints — see
`2026-05-15-cashflow-booking-backend-design.md` §5.1.

```json
{ "ok": true,  "rows": [<row JSON>], "attachments": [<attachment row JSON>] }
{ "ok": false, "error": "<short user-facing>", "detail": "<optional>" }
```

### 5.2 Modified POST endpoints

For each of `/api/cashflow/insert`, `/api/cashflow/amend`,
`/api/loan/insert`, `/api/loan/amend`:

**Request:** `multipart/form-data` with:

- `payload` field: a JSON-encoded string in the same shape as today's
  JSON body (so the existing client code that builds `outputRecord` /
  `loanRecord` is unchanged except for the wrapping).
- `files` field(s): zero or more file uploads.

**Validation (Node, before Drive):**

- File count ≤ 10 (multer)
- Each file ≤ 25 MB (multer)
- Each file's extension matches the allowlist: `.pdf`, `.docx`, `.xlsx`,
  `.png`, `.jpg`, `.jpeg` (case-insensitive). Browser-provided MIME is
  recorded in the row but is not the validation gate (untrusted).
- `payload` must be parseable JSON and must include `deal_ref`.

Any violation returns HTTP 400 with the envelope's `error` field
populated. No Drive calls happen on failure.

**Side effects (Node, in order):**

1. Drive folder ensure (idempotent).
2. Upload each file to Drive.
3. Spawn the existing Python script with stdin:

```json
{
  "payload": { /* identical to today's JSON body */ },
  "attachments": [
    {
      "deal_ref": "MCF-42",
      "drive_folder_id": "1AbC...",
      "drive_folder_url": "https://drive.google.com/drive/folders/1AbC...",
      "file_name": "confirm.pdf",
      "drive_file_id": "1XyZ...",
      "drive_view_url": "https://drive.google.com/file/d/1XyZ.../view",
      "mime_type": "application/pdf",
      "size_bytes": 184321,
      "uploaded_by": "<payload.user_id>"
    }
  ]
}
```

The Python script's existing transaction wraps both the trades_* INSERT
and the per-file `trade_attachments` INSERTs. The `attachments` array
may be empty (booking with no files — fully supported).

**Response:** the existing `rows` plus a new top-level `drive_folder_url`
(empty string if no files were uploaded) and a new `attachments` array
of the inserted attachment rows. Per-row `drive_folder_url` is also
present on each attachment for self-containedness, but the frontend
reads the top-level field.

### 5.3 New GET /api/attachments/:deal_ref

**Request:** `GET /api/attachments/MCF-42`

**Response 200:**

```json
{
  "ok": true,
  "attachments": [
    {
      "deal_ref": "MCF-42",
      "drive_folder_id": "1AbC...",
      "drive_folder_url": "https://drive.google.com/drive/folders/1AbC...",
      "file_name": "confirm.pdf",
      "drive_file_id": "1XyZ...",
      "drive_view_url": "https://drive.google.com/file/d/1XyZ.../view",
      "mime_type": "application/pdf",
      "size_bytes": 184321,
      "status": "uploaded",
      "uploaded_at": "2026-05-19T08:14:22Z",
      "uploaded_by": "PWY"
    }
  ]
}
```

**Response 200 with empty array** if no rows (not 404 — "deal_ref with
zero attachments" is a valid state, and the form needs to know this
without distinguishing "deal_ref doesn't exist").

Only `status='uploaded'` rows are returned (soft-deleted rows are
hidden from the UI).

## 6. Error handling & atomicity

The two-phase nature of upload-then-insert is the core risk. The
contract:

| Failure point | DB state | Drive state | Cleanup |
| ------------- | -------- | ----------- | ------- |
| File validation (Node) | unchanged | unchanged | none needed |
| `ensureFolder` (Node) | unchanged | unchanged | none needed (folder either pre-existed or wasn't created) |
| `uploadFile` partway (Node) | unchanged | some files present | Node deletes the files it already uploaded. If `ensureFolder` *created* the folder this request, also delete the folder. |
| Python script fail (after all uploads succeeded) | rolled back by Python's `ROLLBACK` | all files present | Node deletes all files uploaded this request. If `ensureFolder` *created* the folder this request, also delete the folder. |
| Python success but Node response fails to flush to client (rare) | committed | files present | no cleanup — accept that the booking is real and the client retry will get a 409 via the existing concurrent-amend path |

The "created vs reused folder" distinction matters for amend: an amend
must never delete a pre-existing folder, because that would destroy
earlier attachments. `ensureFolder` returns a `created: boolean` flag
that Node uses to gate the folder-delete branch in cleanup.

Best-effort cleanup failures (Drive returns 5xx on the delete) are
logged with the orphan IDs but do not change the HTTP response. A
later out-of-band GC job can reconcile orphan folders/files against
the `trade_attachments` table.

No in-request retries. The user retries from the form (idempotent due
to `ensureFolder`, so a retry after a transient Drive failure uses the
same folder and just re-uploads the files).

## 7. Frontend changes — `src/TradeBookingForm.jsx`

### 7.1 Submit handler

Today (one of several call sites, all parallel):

```js
const res = await fetch(`/api/${base}/insert`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(outputRecord),
});
```

Changes to:

```js
const fd = new FormData();
fd.append('payload', JSON.stringify(outputRecord));
form.attachments.forEach((a) => {
  if (a._file) fd.append('files', a._file, a.name);
});
const res = await fetch(`/api/${base}/insert`, { method: 'POST', body: fd });
// no explicit Content-Type — browser sets multipart boundary
```

Done for both insert and amend, both cashflow and loan.

### 7.2 Submitted-record panel (currently ~lines 7790–7820)

Today:

```jsx
{submittedRecord.attachments?.length > 0 && (
  <…>{submittedRecord.attachments.length} file(s) queued for Drive upload</…>
)}
```

Replace with:

```jsx
{submittedRecord.drive_folder_url && (
  <div className="…">
    <a href={submittedRecord.drive_folder_url} target="_blank" rel="noreferrer">
      📁 Drive folder — open ↗
    </a>
  </div>
)}
{submittedRecord.attachments?.map((a) => (
  <div key={a.drive_file_id} className="…">
    <span>📄 {a.file_name}</span>
    <span className="opacity-60">{formatBytes(a.size_bytes)}</span>
    <a href={a.drive_view_url} target="_blank" rel="noreferrer">View ↗</a>
  </div>
))}
```

`drive_folder_url` is read from the response's top-level field (see §5.2).

The aspirational footer text (line ~7814: *"On submit → POST multipart
FormData to /api/bookings. Drive service-account uploads each file to
a folder per trade_id; writes back drive_file_id…"*) is rewritten to
describe the actual flow per category, with corrected endpoint names.

### 7.3 Amend mode preload

When the user picks a deal_ref to amend (existing Deal Enquiry flow):

1. After fetching the trade row via `GET /api/cashflow/:deal_ref`,
   parallel-fetch `GET /api/attachments/:deal_ref`.
2. Hydrate `form.attachments` with one entry per existing row:
   ```js
   {
     name: row.file_name,
     size: row.size_bytes,
     status: 'uploaded',
     drive_file_id: row.drive_file_id,
     drive_view_url: row.drive_view_url,
     _file: null,  // marks this as a pre-existing file, not to be re-uploaded
   }
   ```
3. The render path treats entries with `_file === null` as read-only
   (no "remove" button, shows a `View ↗` link instead of a status
   chip). Entries with `_file` set render as today (pending, removable).
4. On amend submit, the FormData-build step (§7.1) only includes
   entries with `_file` truthy — existing files are NOT re-uploaded.

## 8. Config

New env vars consumed by `server/drive.js`:

| Variable | Purpose |
| -------- | ------- |
| `DRIVE_ROOT_FOLDER_ID` | Drive folder ID under which per-deal subfolders are created. Different value for dev / UAT / prod. |
| `GOOGLE_APPLICATION_CREDENTIALS` | Filesystem path to the service-account JSON keyfile. Standard `googleapis` convention — the library reads this env var by default. |

Wired into:

- `start.bat` and `start.sh` — exported before `node server.js`
- `helm_values/base.yaml` — populated from k8s secrets in deployed envs
- `docker/Dockerfile` — keyfile is mounted as a volume, not baked in

If `DRIVE_ROOT_FOLDER_ID` is unset or `GOOGLE_APPLICATION_CREDENTIALS`
points at a missing file, `server.js` exits at startup with a clear
error rather than failing per-request.

Manual one-time setup (documented in `README.md`):

1. Create a GCP service account in the Tokka GCP project; download
   JSON keyfile.
2. Create / pick a Drive folder to serve as `DRIVE_ROOT_FOLDER_ID`.
3. Share that folder with the service-account email as Content manager.
4. Share that folder with the Tokka Workspace group (Viewer) so any
   employee with an org Google login can open `webViewLink`s on the
   subfolders the service account creates.

## 9. Testing

### 9.1 Python — `tests/test_attachments_db.py`

- `insert_attachments` writes N rows with the right column values.
- `get_attachments_for_deal_ref` returns only `status='uploaded'` rows.
- `insert_attachments` is callable inside a caller's open transaction
  (no inner BEGIN/COMMIT).

### 9.2 Node — `tests/server/test-drive.js` (mocks `googleapis`)

- `ensureFolder` returns existing folder when name matches (sets
  `created=false`).
- `ensureFolder` creates and returns when name doesn't match (sets
  `created=true`).
- `uploadFile` calls `files.create` with the right parent.
- `deleteFolder` and `deleteFile` swallow 404s (already-deleted is OK).

### 9.3 Node — `tests/server/test-attachments-validate.js`

- Pure-function tests covering: oversize, over-count, disallowed
  extension, mixed-case extension, no-extension.

### 9.4 Manual smoke (UAT)

1. Book a CASHFLOW with one PDF + one PNG. Verify:
   - Drive folder `<root>/MCF-N/` exists and contains both files.
   - `trade_attachments` has 2 rows for `MCF-N`.
   - Submitted-record panel shows folder link + 2 file rows, all
     clickable, all open in new tab.
2. Amend that booking, add a third file (XLSX). Verify:
   - Same Drive folder now contains 3 files.
   - `trade_attachments` has 3 rows for `MCF-N` (1 new row from this
     amend, the 2 originals untouched).
   - Form panel shows the 2 originals as read-only + the 1 new file.
3. Force a Drive failure (temporarily revoke the service-account
   share on the root folder). Submit a new booking with a file.
   Verify:
   - HTTP 500 returned, with a clear error message.
   - No `trades_cashflow` row inserted.
   - No `trade_attachments` rows inserted.
   - Best-effort cleanup attempt logged.
4. Book a CASHFLOW with **zero** files. Verify it still works (no
   Drive folder created, no `trade_attachments` rows, submitted-record
   panel shows no attachments section).
