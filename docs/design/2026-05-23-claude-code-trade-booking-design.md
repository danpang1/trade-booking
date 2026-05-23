# Trade Booking via Claude Code

**Date:** 2026-05-23
**Status:** Approved (brainstorming complete, ready for implementation plan)
**Scope:** Allow any authenticated trade-booking user to submit SPOT and CASHFLOW trades from Claude Code. Submissions land as drafts in a new pending queue, reviewed and approved by the same user in the existing React app, then inserted into the live `trades_spot` / `trades_cashflow` tables via the existing tested insert path.

---

## 1. Motivation

Today, every trade booking starts in the React form. For high-volume days — e.g., a batch of 6 OTC cashflows posted in a Slack thread — that means six full form fills, each a chance for fat-finger errors. A Claude Code-driven path lets users dictate trades in natural language ("book 10 BTC spot at 95k on Binance, portfolio 8006"), and submit single or batched bookings as **drafts** that the same user reviews and approves in-app before they go live.

Critically, the existing form behavior is **unchanged**. The new capability is purely additive — only Claude-Code-originated bookings flow through the new draft + approve queue. Form bookings keep their direct-insert behavior.

---

## 2. Decisions taken during brainstorming

| Decision | Choice | Rationale |
|---|---|---|
| v1 trade types | SPOT + CASHFLOW | Two most common manual bookings; FUTURE/LOAN added later |
| Approval model | Self-approval | Same user who submitted via Claude Code reviews their own drafts. Maker-checker is a bigger workflow change and can be added later |
| Existing form behavior | Unchanged | Only Claude-Code bookings go to draft. Form keeps direct-insert path |
| Distribution architecture | Claude Code **plugin** + personal token (not hosted MCP server) | Reuses existing API/auth/deployment. No new service to operate. Plugin can be migrated to MCP later without changing the API surface |
| Draft storage | New `bookings_draft` table with `category` + JSONB `payload`. **Not** a new status on `trades_spot/cashflow` | Keeps trade tables and existing scripts untouched. Approved drafts INSERT into trade tables via the existing tested `*_insert.py` path |
| Batch bookings | First-class. Single `POST /api/bookings/draft/batch` endpoint, shared `batch_id`, all-or-nothing on submit, per-row on approve | Without batching, "book these 6 cashflows" requires 6 separate calls and the resulting drafts have no on-page grouping |
| Auth for Claude Code | Long-lived personal tokens (Bearer auth) alongside the existing `sid` cookie; both resolve to the same `user_id` | Server keeps the "user_id is unforgeable" invariant. Tokens are revocable, prefixed (`tkmo_`), and stored hashed |
| Phase 0 standalone | Yes — ship token system + Bearer auth before any Claude Code work | Lower risk; tokens infra is proven before any draft endpoints depend on it. Tokens settings page is useful on its own |
| Edit-in-form on pending page | Yes — power-user escape hatch | "Open in form" button opens `TradeBookingForm.jsx` pre-filled with draft payload, full editing, then book |
| Rollout cadence | Staged: dogfood 1 week, then expand 2–3 users/wk | Surfaces UX issues gradually; install docs improve cohort-over-cohort |

---

## 3. Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  Alice's laptop                                                       │
│                                                                       │
│   ┌─ Claude Code ───────────────────────────────┐                    │
│   │  • trade-booking skill (markdown)           │                    │
│   │  • slash commands /book /drafts /login      │                    │
│   │                                              │                    │
│   │  shells out to ▶                            │                    │
│   │   ┌─ tokka-mo CLI ────────────────────────┐ │                    │
│   │   │ login | logout | book | drafts | ...  │ │                    │
│   │   │ creds: ~/.config/tokka-mo/credentials │ │                    │
│   │   │ refdata cache: ~/.cache/tokka-mo/     │ │                    │
│   │   └─────────────┬──────────────────────────┘ │                    │
│   └─────────────────┼─────────────────────────────┘                    │
│                     │ HTTPS · Authorization: Bearer tkmo_...           │
│                     ▼                                                  │
└─────────────────────┼──────────────────────────────────────────────────┘
                      │
┌─────────────────────┼──────────────────────────────────────────────────┐
│                     │                                                   │
│   ┌─ Browser (React) ──────────────────────────────────────┐          │
│   │  existing TradeBookingForm + new <PendingDrafts>       │          │
│   │  + new <ApiTokens> settings page                       │          │
│   └────────────────────┬───────────────────────────────────┘          │
│                        │ Cookie: sid=...                                │
│                        ▼                                                │
│   ┌─ server.js ──────────────────────────────────────────────────────┐ │
│   │  auth middleware: cookie OR Bearer → resolve to user             │ │
│   │  new routes: /api/tokens, /api/bookings/draft, /draft/batch,     │ │
│   │              /drafts, /drafts/:id, /:id/approve, /:id/reject     │ │
│   └────────────────────┬─────────────────────────────────────────────┘ │
│                        ▼                                                │
│   ┌─ Python scripts ────────────────────────────────────────────────┐ │
│   │  new: token_create.py, token_list.py, token_revoke.py,          │ │
│   │       draft_insert.py, draft_batch_insert.py, draft_list.py,    │ │
│   │       draft_get.py, draft_patch.py, draft_approve.py,           │ │
│   │       draft_reject.py, apply_schema_drafts.py,                   │ │
│   │       apply_schema_api_tokens.py                                 │ │
│   │  draft_approve.py calls existing spot_insert.py /                │ │
│   │       cashflow_insert.py — the *same* path the form uses         │ │
│   └────────────────────┬─────────────────────────────────────────────┘ │
│                        ▼                                                │
│                Postgres UAT/PROD                                        │
│      (new tables: bookings_draft, api_tokens; trades_* untouched)       │
└─────────────────────────────────────────────────────────────────────────┘
```

**Key invariants:**

- `user_id` / `created_by` on every booking continues to be set server-side from the authenticated session, never trusted from request body. Bearer auth honors this exactly like cookie auth.
- The live trade tables (`trades_spot`, `trades_cashflow`) have **zero schema changes** and only ever receive data through the existing `*_insert.py` scripts. Whether a row came from the form or from a Claude-Code-approved draft, it took the same code path.
- Drafts are isolated per user: every list/get/edit/approve endpoint filters by `created_by = current_user`. No admin-sees-all in v1 (can be added later without breaking changes).

---

## 4. Data model

Postgres UAT/PROD, same DB as the existing trade tables. **Not bitemporal** — drafts are operational state, not historical record.

### 4.1 `bookings_draft`

```sql
CREATE TABLE bookings_draft (
  id                  SERIAL          PRIMARY KEY,
  category            TEXT            NOT NULL
                        CHECK (category IN ('SPOT','CASHFLOW')),
  payload             JSONB           NOT NULL,
  source              TEXT            NOT NULL
                        CHECK (source IN ('CLAUDE_CODE')),
  status              TEXT            NOT NULL
                        CHECK (status IN
                          ('PENDING_REVIEW','APPROVED','REJECTED')),
  batch_id            UUID,                    -- NULL = single; shared across a batch
  client_request_id   UUID            NOT NULL UNIQUE,
  created_by          VARCHAR(64)     NOT NULL,
  created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
  approved_at         TIMESTAMPTZ,
  approved_by         VARCHAR(64),
  approved_deal_ref   TEXT,                    -- MFX/MCF ref of the inserted live trade
  rejected_at         TIMESTAMPTZ,
  rejected_by         VARCHAR(64),
  rejection_reason    TEXT
);

CREATE INDEX idx_drafts_user_status
  ON bookings_draft (created_by, status);
CREATE INDEX idx_drafts_batch
  ON bookings_draft (batch_id)
  WHERE batch_id IS NOT NULL;
CREATE INDEX idx_drafts_pending
  ON bookings_draft (created_by, created_at DESC)
  WHERE status = 'PENDING_REVIEW';
```

**Notes:**
- `payload` carries the exact JSON shape the form would have sent — same field names, same types. This is what guarantees the approve path can call the existing `*_insert.py` scripts unmodified.
- `client_request_id` is supplied by the plugin (one UUID per draft, even in a batch) and is `UNIQUE`. Retries with the same UUID are a no-op; the server returns the existing draft.
- Approved drafts are kept indefinitely (audit). `approved_deal_ref` links back to the live row in `trades_spot` / `trades_cashflow`.
- Rejected drafts are purged after 7 days by a future cleanup job (out of scope for v1; just retained).

### 4.2 `api_tokens`

```sql
CREATE TABLE api_tokens (
  id            SERIAL          PRIMARY KEY,
  user_id       INTEGER         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash    VARCHAR(64)     NOT NULL UNIQUE,   -- sha256 hex of plaintext
  token_prefix  VARCHAR(16)     NOT NULL,          -- e.g. "tkmo_a1b2"
  name          VARCHAR(64)     NOT NULL,
  created_at    TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
  last_used_at  TIMESTAMPTZ,
  expires_at    TIMESTAMPTZ     NOT NULL,
  revoked_at    TIMESTAMPTZ
);

CREATE INDEX idx_api_tokens_user
  ON api_tokens (user_id)
  WHERE revoked_at IS NULL;
CREATE INDEX idx_api_tokens_lookup
  ON api_tokens (token_hash)
  WHERE revoked_at IS NULL AND expires_at > NOW();
```

**Token format:** `tkmo_` + 32 random url-safe bytes (~43 chars after base64url). Plaintext is shown to the user **once** at creation; only `sha256(plaintext)` is stored. Lookup uses the `idx_api_tokens_lookup` partial index on the hash for sub-ms validation.

**Default expiry:** 90 days. Configurable per-token at creation: 30 days / 90 days / 1 year.

### 4.3 `trades_spot`, `trades_cashflow`, `users`, `sessions`

**No changes.** Existing schemas and `*_insert.py` scripts are reused verbatim.

---

## 5. API surface

### 5.1 Auth middleware (server.js)

The existing auth middleware resolves a request's `req.user` from the `sid` cookie. It is extended to also accept:

```
Authorization: Bearer tkmo_<43 chars>
```

Resolution order: cookie first (if present and valid), then Bearer. Both produce the same `req.user = {id, username, role}` object — downstream handlers don't know which auth was used.

Bearer validation:
1. Strip `Bearer ` prefix; compute `sha256(token)`.
2. `SELECT user_id FROM api_tokens WHERE token_hash=$1 AND revoked_at IS NULL AND expires_at > NOW()`.
3. On match: `UPDATE api_tokens SET last_used_at = NOW() WHERE id = …` (best-effort, fire-and-forget).
4. Load user from `users` table; attach to `req.user`.

### 5.2 Token endpoints (cookie auth only)

| Method | Path | Body | Returns |
|---|---|---|---|
| `POST` | `/api/tokens` | `{name, expires_in_days}` | `{id, token, prefix, name, expires_at}` — `token` plaintext returned **once** |
| `GET` | `/api/tokens` | — | `[{id, prefix, name, created_at, last_used_at, expires_at, revoked_at}]` |
| `DELETE` | `/api/tokens/:id` | — | `204` |

`POST /api/tokens` is the only endpoint that ever returns plaintext. The React app shows it in a modal with a copy button and a "I've saved it" gate before closing.

### 5.3 Draft endpoints (cookie OR Bearer)

| Method | Path | Body | Returns |
|---|---|---|---|
| `POST` | `/api/bookings/draft` | `{category, payload, client_request_id}` | `{draft_id, review_url}` |
| `POST` | `/api/bookings/draft/batch` | `{trades: [{category, payload, client_request_id}, ...]}` | `{batch_id, created, draft_ids, review_url}` |
| `GET` | `/api/bookings/drafts` | query: `?status=&batch_id=` | `[{id, category, status, batch_id, payload, created_at, ...}]` |
| `GET` | `/api/bookings/drafts/:id` | — | `{id, category, status, payload, ...}` |
| `PATCH` | `/api/bookings/drafts/:id` | `{payload}` | `{id, ...}` — only allowed when `status='PENDING_REVIEW'` |
| `POST` | `/api/bookings/drafts/:id/approve` | — | `{id, status:'APPROVED', deal_ref}` |
| `POST` | `/api/bookings/drafts/:id/reject` | `{reason?}` | `{id, status:'REJECTED'}` |

**Per-user isolation:** Every list/get/patch/approve/reject filters by `created_by = req.user.username` and returns `404` for drafts owned by other users. No admin override in v1.

**Approve flow (atomic):**

```sql
BEGIN;

  -- Step 1: claim the draft atomically; bail if already approved/rejected
  UPDATE bookings_draft
     SET status = 'APPROVED', approved_at = NOW(), approved_by = $user
   WHERE id = $id
     AND created_by = $user
     AND status = 'PENDING_REVIEW'
  RETURNING category, payload;

  -- (If 0 rows: ROLLBACK and return 409 "already approved or not found")

  -- Step 2: insert into live trade table via existing logic
  --   draft_approve.py spawns spot_insert.py or cashflow_insert.py
  --   passing the payload as input. The insert script returns the deal_ref.
  --   We update the draft row with approved_deal_ref afterward.

COMMIT;
```

If the insert script fails (constraint violation, refdata mismatch), the whole transaction rolls back: the draft stays in `PENDING_REVIEW` and the error surfaces in the UI. The user can edit and retry.

**Batch submit (atomic):**

```python
# draft_batch_insert.py
with conn.transaction():
    batch_id = uuid4()
    draft_ids = []
    for trade in trades:
        # client_request_id uniqueness check — return existing if dup
        existing = SELECT id FROM bookings_draft WHERE client_request_id = trade.client_request_id
        if existing:
            draft_ids.append(existing.id)
            continue
        # validate payload shape against category schema
        validate_payload(trade.category, trade.payload)  # raises on bad
        # insert
        row = INSERT INTO bookings_draft (...) RETURNING id
        draft_ids.append(row.id)
    # If any validate_payload raised: the transaction rolls back, nothing inserted.
return {batch_id, created: len(trades), draft_ids, review_url}
```

`validate_payload` does **shape** validation only: required fields present, types correct, enums valid. It does **not** validate against refdata — that's the plugin's job (already done before submit) and the existing `*_insert.py` scripts' job (enforced at approve time).

---

## 6. Pending page UX

Two new pages added to the React app. Both follow the existing Bloomberg-terminal aesthetic (orange `#FA8C16` accent, JetBrains Mono, sharp rectangles, `BB` theme tokens).

### 6.1 `/pending` — Drafts inbox

New top-level nav item: `PENDING (N)` where N is the user's count of `PENDING_REVIEW` drafts. Badge polls every 30 seconds.

Layout:

```
┌─ PENDING DRAFTS · alice ─────────────────────────────── [refresh] ──┐
│                                                                      │
│ ── BATCH bat-xy7z · 6 drafts · 2 min ago ──────────────────────────│
│ │ ☐ │ #1234 │ CF IN  100k  USDT  CptyA  Tron     │ [Edit][Open in form][✓]│
│ │ ☐ │ #1235 │ CF OUT  50k  USDC  CptyB  Eth      │ [Edit][Open in form][✓]│
│ │ ☐ │ #1236 │ CF IN   25k  USDC  CptyA  Tron     │ [Edit][Open in form][✓]│
│   (3 more)                                                          │
│   [Approve all 6]   [Reject all]                                    │
│                                                                      │
│ ── SINGLE · 4 hrs ago ────────────────────────────────────────────│
│ │   │ #1228 │ SPOT BUY 10  BTC/USDT 95k  Binance │ [Edit][Open in form][✓]│
│                                                                      │
│ ── APPROVED · last 7 days ──────────────────── [show / hide] ─────│
│   (collapsed by default; shows approved_deal_ref linking to trade)  │
│                                                                      │
│ ── REJECTED · last 7 days ──────────────────── [show / hide] ─────│
│   (collapsed by default)                                            │
└─────────────────────────────────────────────────────────────────────┘
```

**Actions:**

- **Edit** — opens an in-place modal with the draft's payload as a form. Same field components as `TradeBookingForm.jsx` but rendered in a modal with a "Save Draft" button (PATCH). For minor tweaks.
- **Open in form** — navigates to `/?draft=<id>`. `TradeBookingForm.jsx` is extended with a third mode (alongside `new` and `amend`) called `draft`: loads the payload, allows full editing, the submit button is **"Save Draft"**. From there the user can also click **"Approve & Book"** to push through the approve path. This is the power-user escape hatch.
- **Approve (✓)** — shows a small confirmation popover; on confirm, calls `/approve` and the row vanishes from `PENDING_REVIEW`.
- **Approve all N** — loops through per-draft approve; reports per-row results. Successful rows are removed; failed rows stay with an inline error.
- **Reject** / **Reject all** — optional reason text field; otherwise same as approve.

**Empty state** doubles as discovery:

```
   No pending drafts.

   Use Claude Code to book trades:
   $ claude
   > "book 10 BTC spot at 95k on Binance, portfolio 8006"

   [Install Claude Code plugin →]   [Manage API tokens →]
```

### 6.2 `/settings/tokens` — API tokens

Reached via a user-menu link (top right, alongside Logout). Style follows `UserAdmin.jsx`.

```
┌─ MY API TOKENS ────────────────────────────────────────────────────┐
│                                            [+ GENERATE NEW TOKEN]  │
│  NAME             PREFIX        LAST USED      EXPIRES        ___  │
│  Alice's MacBook  tkmo_a1b2...  5 min ago      2026-08-21    [×]  │
│  Alice's iPad     tkmo_c3d4...  12 days ago    2026-08-21    [×]  │
└─────────────────────────────────────────────────────────────────────┘
```

Generate modal asks for `name` + `expires_in_days` (30 / 90 / 365). On success, opens a one-shot reveal modal: plaintext token, copy button, "I've saved it" dismisses the modal — the token is **not retrievable** after this point.

Revoke is one click + confirmation; effective immediately (next request with that token fails 401).

### 6.3 `TradeBookingForm.jsx` — third mode

Currently the form has two modes: `new` (default) and `amend` (when editing an existing trade). Add a third: `draft`.

| Mode | Loads from | Submit button | On submit |
|---|---|---|---|
| `new` | (empty) | "Book Trade" | `POST /api/bookings/spot` or `/cashflow` → live trade |
| `amend` | live trade row | "Amend" | bitemporal amend on `trades_*` |
| `draft` | draft row | "Save Draft" + "Approve & Book" | PATCH draft payload / POST approve |

The mode is driven by the URL: `/` → new, `/?amend=<deal_ref>` → amend, `/?draft=<id>` → draft.

---

## 7. Claude Code plugin

New Bitbucket repo `tokka-mo-claude-plugin`.

### 7.1 Repo layout

```
.claude-plugin/
  plugin.json
skills/
  trade-booking/
    SKILL.md
    references/
      spot-schema.md
      cashflow-schema.md
      examples.md
commands/
  book.md
  drafts.md
  login.md
bin/
  tokka-mo            # Python 3.10+ CLI (single-file script)
  tokka-mo.bat        # Windows shim
install.sh            # one-line installer for macOS/Linux
README.md
```

### 7.2 The trade-booking skill

Activates automatically when a user mentions booking, trades, drafts, or runs a `/book` command. Loaded into Claude's context as markdown. Holds:

- **Field reference** — required and optional fields per category, lifted from `apply_schema_spot.py` and `apply_schema_cashflow.py`. Single source of truth.
- **Validation rules** — `base_asset ≠ quote_asset`; `direction ∈ {LONG, SHORT}` for SPOT and `{INCOMING, OUTGOING}` for CASHFLOW; `price` consistent with `base_amount × price = quote_amount` within tolerance; date parsing rules; etc.
- **The workflow:**
  1. Parse user input → list of structured trades (1 or N)
  2. For each trade: identify missing required fields; ask user to supply
  3. Validate each trade against the locally-cached refdata (`~/.cache/tokka-mo/refdata.json`)
  4. **Show structured preview to the user, ask for explicit "y" confirmation** ← in-CC checkpoint
  5. On `y`: shell out to `tokka-mo book` (or `book-batch` if N>1)
  6. Report back the draft ID(s) + review URL

The skill never makes HTTP calls itself. All network I/O goes through `tokka-mo`.

### 7.3 The `tokka-mo` CLI

Single-file Python 3.10+ script. Responsibilities:

- **Credential storage:** `~/.config/tokka-mo/credentials` (JSON, `chmod 600`), containing `{api_url, username, token}`.
- **Refdata cache:** `~/.cache/tokka-mo/refdata.json`, refreshed automatically if older than 24h, or on `tokka-mo refdata refresh`. Source: the existing static `/refdata/*.json` endpoints.
- **HTTP calls:** all requests carry `Authorization: Bearer <token>`. Timeouts: 10s. Retries on 5xx with exponential backoff (3 attempts). 401 prints a clear message: "Token expired or revoked. Run: tokka-mo login".

Commands:

```
tokka-mo login                            # interactive: username/pw → mints token → saves
tokka-mo logout                           # DELETE /api/tokens/:id → clear local creds
tokka-mo whoami                           # GET /api/auth/whoami
tokka-mo refdata refresh                  # pull /refdata/*.json → cache
tokka-mo book < payload.json              # POST /api/bookings/draft
tokka-mo book-batch < batch.json          # POST /api/bookings/draft/batch
tokka-mo drafts list [--batch <id>]       # GET /api/bookings/drafts → text table
```

### 7.4 Slash commands

Sugar over the skill. Not required for the common path (the skill auto-activates from plain English).

- `/book` — same flow as plain English; just shorter to type.
- `/drafts` — invokes `tokka-mo drafts list`; renders the result as a Claude-Code table.
- `/login` — invokes `tokka-mo login` for first-time setup.

### 7.5 Distribution & install

```bash
# One-time install per user/laptop
git clone ssh://git@bitbucket.org/tokkalabs/tokka-mo-claude-plugin.git \
  ~/.claude/plugins/tokka-mo
~/.claude/plugins/tokka-mo/install.sh
# - registers plugin with Claude Code (settings.json)
# - adds tokka-mo to PATH
# - creates ~/.config/tokka-mo/ and ~/.cache/tokka-mo/

# First-time auth
claude  # then: /login (or: tokka-mo login)
```

Updates: `cd ~/.claude/plugins/tokka-mo && git pull`. For v1 this is acceptable for a small team; an auto-updater can be added later if needed.

Windows users: `install.sh` has a `.bat` counterpart; CLI logic is OS-agnostic Python.

---

## 8. Phasing & rollout

| Phase | Duration | Deliverables | Done when |
|---|---|---|---|
| **0. Foundation** | ~1 wk | `apply_schema_api_tokens.py`, `api_tokens` table, Bearer auth middleware in `server.js`, `POST/GET/DELETE /api/tokens`, `<ApiTokens>` settings page in React | A user can generate, view, and revoke tokens in the React app. Smoke test: `curl -H "Authorization: Bearer <token>" /api/auth/whoami` returns user info |
| **1. CASHFLOW draft + batch, end-to-end** | ~1.5–2 wk | `apply_schema_drafts.py`, `bookings_draft` table, all draft endpoints (single **and** batch, CASHFLOW only), `draft_approve.py` invoking `cashflow_insert.py`, `<PendingDrafts>` page in React with batch grouping, `TradeBookingForm.jsx` `draft` mode for CASHFLOW, plugin v0.1 (CASHFLOW, single + batch) | One dogfooder can book a 6-trade CASHFLOW batch in Claude Code in UAT, see the batch grouped on `/pending`, approve-all, all 6 land in `trades_cashflow` |
| **2. SPOT support** | ~3–5 d | SPOT handling in plugin skill + `draft_approve.py`, SPOT field validation, `TradeBookingForm.jsx` `draft` mode extended to SPOT, plugin v0.5 (SPOT + CASHFLOW) | Same dogfooder can book a SPOT trade in Claude Code, review on `/pending`, approve, and see it land in `trades_spot`. Batch works for SPOT too (the endpoint and pending grouping are already in place from Phase 1) |
| **3. Polish & rollout** | ~3–5 d | Idempotency hardening, plugin error UX, install one-liner, README, rollout docs, expand to 2–3 more users | First non-dogfood cohort can install and book without help. Issues filed are tracked but not blocking |

**Rollout:** dogfood (1 user) for 1 week → first cohort (2–3 users) for 1 week → next cohort (2–3 users) → … Each cohort feeds back into install docs. Plugin auto-update is **not** in v1; users `git pull` when notified of releases.

**Total: ~4–5 weeks** from start of Phase 0 to "everyone on the team can use it."

---

## 9. Risks & mitigations

| # | Risk | Mitigation |
|---|---|---|
| 1 | LLM hallucinates a valid-looking but wrong value (wrong portfolio, stale counterparty) | Four checkpoints: (a) plugin validates against refdata cache before submit; (b) plugin shows structured preview and requires `y` confirmation in Claude Code; (c) `/pending` is the formal human review; (d) approve requires explicit click. The plugin can't silently book |
| 2 | Refdata cache goes stale | 24h TTL on local cache; manual `tokka-mo refdata refresh`; server-side `*_insert.py` validates at approve time regardless |
| 3 | Token compromise (screenshare leak, accidental commit, etc.) | 90-day default expiry; one-click revoke (effective immediately); `last_used_at` logged; plaintext shown only at creation |
| 4 | Server schema drift ahead of plugin (new required field) | Server returns field-level error messages; plugin surfaces them with "looks like a new field is required". `/pending` edit is always the escape hatch |
| 5 | Race: user clicks Approve twice (double-click, two tabs) | Approve uses atomic `UPDATE ... WHERE status='PENDING_REVIEW' RETURNING *`. First click wins; second gets a clean 409 |
| 6 | Same batch submitted twice (user retypes a similar request) | Per-trade `client_request_id` UUID dedupes within a batch. Cross-batch dedupe is not auto-detected; human review on `/pending` is the catch (user sees 12 drafts where 6 expected) |
| 7 | `TradeBookingForm.jsx` complexity (3 modes: new, amend, draft) | Each mode well-typed; add UI tests per mode; if file grows unwieldy, split into mode-specific components in a follow-up |
| 8 | Install friction for non-technical users (git clone, PATH, etc.) | `install.sh` one-liner; if a few users struggle, package as a self-contained binary in Phase 3+ |
| 9 | Plugin and server versions diverge across the team | `tokka-mo whoami` returns server version + minimum-required plugin version; plugin warns on mismatch |

---

## 10. Out of scope (v1)

- **Maker-checker approval** (peer or admin reviews someone else's draft) — possible future enhancement; would add `approval_required_by` field, role checks, and routing logic. Current per-user isolation makes adding this non-breaking.
- **FUTURE and LOAN trade types** — same machinery, just more category-specific schema in the plugin's skill and a CHECK constraint update on `bookings_draft.category`.
- **MCP server transport** — keep the plugin design; if/when MCP becomes the preferred shape, the MCP server can call the same `/api/bookings/draft` endpoints. No API changes needed.
- **Real-time push** of new drafts to the React app — v1 polls the pending count every 30s. Websockets / SSE can be added later.
- **Admin "see all drafts" view** — strict per-user isolation in v1. Adding an admin role override later is a one-line change to the `WHERE created_by = …` clause.
- **Auto-update for plugin** — `git pull` for v1; package manager or self-update mechanism later.
- **Attachments on drafts** — the existing app supports attachments on live trades; draft-time attachments are out of scope. Users add attachments at approval/edit time via "Open in form".
- **Rejection comments going back to Claude Code** — v1 reject is silent from the plugin's perspective. Future: `tokka-mo drafts list --status=rejected` could show reasons.
- **Multi-user batches** (one user submits, another approves each row) — not supported; batches are per-submitter, approved by the submitter.

---

## 11. Open questions for implementation planning

- Where exactly does the `<PendingDrafts>` component mount in the existing React app? (Likely a new sibling of `<TradeBookingForm>` inside `<Authenticated>`.)
- What's the exact JSON shape returned by `/refdata/*.json` today? (The plugin's validation logic depends on this. Confirm during Phase 1.)
- Token plaintext format: just `tkmo_<43 url-safe chars>`, or include a checksum suffix for malformed-token detection? (Lean toward simple; revisit if support requests pile up.)
- Bitbucket repo permissions for the plugin: who can read/clone? Team-wide read is required for the install one-liner to work.
- Helm chart bump strategy: ship Phase 0 → bump → Phase 1 → bump, or staged per phase? (Existing pattern bumps per non-trivial change, so per phase.)
