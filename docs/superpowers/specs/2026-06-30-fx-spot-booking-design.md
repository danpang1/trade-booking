# FX / SPOT Trade Booking via the trade-booking skill — Design

- **Date:** 2026-06-30
- **Author:** danny.pang (with Claude Code)
- **Status:** Approved for planning
- **Repo:** `middle-office-tools` (deployed copy; also holds the `tokka-mo` plugin source)

## Goal

Let users book SPOT (incl. FX-style stablecoin/fiat swaps, e.g. `USDC → USDG @ 1.00`)
through the existing `trade-booking` skill, end-to-end: a SPOT draft can be created
from Claude Code **and** approved/booked into `trades_spot` from the Middle Office app.

Today the plugin is CASHFLOW-only and the server deliberately stubs SPOT in two
places. This design un-stubs the server and generalizes the plugin CLI + skill to be
category-aware, reusing the already-built `spot_db` / `spot_insert` / React SPOT form.

## Non-goals

- No changes to the React `TradeBookingForm.jsx` (the SPOT UI already exists). This
  avoids the known "two diverging copies" hazard, which only applies to that file.
- No new SPOT refdata source (pairs are free-form `base_asset` + `quote_asset`
  validated against the existing tokens cache).
- No new draft schema/table (the `bookings_draft` table already stores `category`).
- SPOT amendment via the skill is out of scope (amend still goes through the app).

## Confirmed decisions

1. **Scope:** Full end-to-end — plugin + server un-stub.
2. **Swap mapping convention:** *received asset = `base_asset`, `direction = LONG`.*
   `Swap A to B @ price` ⇒ give A, receive B ⇒ `base_asset=B`, `quote_asset=A`,
   `direction=LONG`, `price` = quote-per-base. Enforce `base_amount × price == quote_amount`.
3. **Mixed pastes:** one mixed batch — each row tagged with its own `category`,
   submitted as a single `book-batch`; one `batch_id` covers all rows.
4. **CLI shape:** Approach A — category-aware generalization of `book` / `book-batch`
   (explicit per-row `category`), not separate `book-spot` commands.
5. **Account optionality:** SPOT `account` / `account_type` / `counterparty` remain
   **optional** (matching server `REQUIRED_FIELDS_INSERT`). The skill *asks* for an
   account when the user names a venue (e.g. "on Paxos") but allows booking without one.

## Architecture & data flow

No new components. The SPOT path rides the existing draft pipeline.

```
Claude (trade-booking skill)
  → parse NL → SPOT/CASHFLOW payload(s) + per-row "category"
  → preview → require `y`
  → ${PLUGIN_ROOT}/bin/tokka-mo book | book-batch   (category-aware)
       → POST /api/bookings/draft[/batch]   {category, payload, client_request_id}
            → draft_insert / draft_batch_insert
                 → draft_db.validate_payload_for_category(category, payload)   [un-stub SPOT]
                 → INSERT bookings_draft (category, payload, ...) status=PENDING_REVIEW
  ── later, in MO app ──
  approver clicks Approve
       → draft_approve.py → route by category → spot_insert._insert_one   [un-stub SPOT]
            → trades_spot (SCD2, deal_ref MFX-<n>)
```

Edit sites:

| Layer | File | Change |
| --- | --- | --- |
| Server | `scripts/draft_db.py` | Wire SPOT branch in `validate_payload_for_category` → `spot_db.validate_payload(payload, mode="insert")`; add `import spot_db`. |
| Server | `scripts/spot_insert.py` | Refactor: extract `_insert_one(cur, payload) -> dict` (the INSERT … RETURNING + `row_to_payload`) so it is reusable inside another transaction; `main()` calls it. **It does not exist today** — only `main()` does. |
| Server | `scripts/draft_approve.py` | Import the new `spot_insert._insert_one`; dispatch by `category` (CASHFLOW / SPOT), drop the SPOT rejection. |
| Plugin CLI | `plugin/bin/tokka-mo` | Add SPOT enums + `validate_spot_payload`; a `validate(category, payload, refdata)` dispatcher; `--category` on `book`; per-row category in `book-batch`; remove hardcoded `"category": "CASHFLOW"`. |
| Skill | `plugin/skills/trade-booking/SKILL.md` | Drop CASHFLOW-only gating; add SPOT/swap parsing, auto-fill, preview, mixed-batch grouping. |
| Skill | `plugin/skills/trade-booking/references/spot-schema.md` (new) + `examples.md` | SPOT field contract + worked swap example. |

Reused unchanged: `scripts/spot_db.py`, `src/TradeBookingForm.jsx`,
the `/api/bookings/draft[/batch]` routes, `draft_insert.py`, `draft_batch_insert.py`.
(`spot_insert.py` is refactored but its `main()` behavior is preserved.)

## Server changes (detail)

### `draft_db.py`

`CATEGORIES` already includes `"SPOT"`. Replace the SPOT stub in
`validate_payload_for_category`:

```python
if category == "SPOT":
    try:
        spot_db.validate_payload(payload, mode="insert")
    except spot_db.ValidationError as e:
        raise ValidationError(str(e)) from e
    return
```

Add `import spot_db` next to `import cashflow_db`.

### `spot_insert.py` (refactor — prerequisite for approve)

Today the INSERT lives inline in `main()`. Extract it to mirror
`cashflow_insert._insert_one`:

```python
def _insert_one(cur, payload: dict) -> dict:
    cols, vals = spot_db.payload_to_columns(payload)
    col_list = ", ".join(cols + ("effective_start", "effective_end"))
    placeholders = ", ".join(["%s"] * len(cols)) + ", NOW(), NULL"
    cur.execute(
        f"INSERT INTO trades_spot ({col_list}) VALUES ({placeholders}) RETURNING *",
        vals,
    )
    out_cols = [d.name for d in cur.description]
    return spot_db.row_to_payload(out_cols, cur.fetchone())
```

`main()` then calls `row = _insert_one(cur, payload)` inside its existing
`with conn`/cursor block, and keeps the attachments step
(`attachments_db.insert_attachments`) after it. Attachments stay in `main()`
(drafts carry none, so `draft_approve` does not need them).

### `draft_approve.py`

Add `from spot_insert import _insert_one as spot_insert_one`. Replace the
`if category != "CASHFLOW": raise ...` block with a dispatch:

```python
if category == "CASHFLOW":
    inserted = cashflow_insert_one(cur, payload)
elif category == "SPOT":
    inserted = spot_insert_one(cur, payload)
else:
    raise draft_db.ValidationError(f"approve not implemented for category {category}")
```

## Plugin CLI changes (detail)

Mirror the cashflow surface for SPOT:

- **Constants:** `VALID_SPOT_DIRECTIONS = {"LONG", "SHORT"}`; reuse `VALID_STATUSES`,
  `VALID_ACCOUNT_TYPES`. `REQUIRED_SPOT_FIELDS` = direction, entity, portfolio_id,
  portfolio_name, base_asset, base_amount, quote_asset, quote_amount, price,
  trade_date, value_date, user_id, status.
- **`validate_spot_payload(payload, refdata)`** — mirrors `spot_db._validate_one`
  (required present, direction/status enums, numeric base/quote/price/fee,
  `base_asset != quote_asset`, integer portfolio_id) **plus** refdata checks:
  - `portfolio_id` ∈ refdata portfolio numbers; `portfolio_name` matches that row
    (reuse `_refdata_portfolio_ids`).
  - `base_asset`, `quote_asset`, and `fee_asset` (if present) ∈ tokens.
  - If `account` present: `account` ∈ accounts and `account_type` ∈ VALID_ACCOUNT_TYPES.
  - If `counterparty` present: ∈ counterparties (named — not the digit-string rule).
  - `base_amount × price == quote_amount` within a small relative tolerance.
- **Dispatcher** `validate(category, payload, refdata)` → cashflow or spot validator.
- **`cmd_book`:** add `--category` (choices CASHFLOW/SPOT, default CASHFLOW). Validate
  and POST with that category.
- **`cmd_book_batch`:** read each trade's own `category` (default CASHFLOW if absent),
  validate per row with the dispatcher, build `prepared` with per-row category. Remove
  the two hardcoded `"category": "CASHFLOW"` lines. CRID dedupe + UUID logic unchanged.

## Skill changes (detail)

- **Activation:** remove the "CASHFLOW only / SPOT in Phase 2" bail; activate on
  spot / swap / FX / buy / sell wording too.
- **Parse → SPOT payload:**
  - Swap form `Swap <amtA> <A> to <amtB> <B> [on <venue>] [@ <price>]` ⇒ `direction=LONG`,
    `base_asset=B`, `base_amount=amtB`, `quote_asset=A`, `quote_amount=amtA`,
    `price` = quote-per-base (derive if omitted via `amtA/amtB`). Enforce
    `base_amount × price == quote_amount`.
  - Buy/sell form `buy/sell <amt> <X> at <P> [quote <Q>]` ⇒ LONG for buy / SHORT for sell.
  - Auto-fill `entity` + `portfolio_name` from the refdata portfolio row; omit
    `txn_type` (server defaults SPOT); `status=PENDING`; user_id set by CLI.
- **Missing-field round:** ask once for portfolio, and base/quote/amount/price if not
  derivable. If a venue is named ("on Paxos"), resolve to that venue's account and set
  `account_type`; otherwise book without an account.
- **Preview:** SPOT block (direction, base/quote/price, account/venue, fees). Mixed
  pastes grouped under `CASHFLOW (n)` / `SPOT (n)` with numbered rows. One `y`, one
  `book-batch`, per-row category.
- **References:** new `references/spot-schema.md` (condensed from
  `docs/spot-schema-mapping.md`) + a SPOT swap example in `references/examples.md`.

## Validation & error handling

Two-layer validation preserved: the CLI catches typos before the round-trip; `spot_db`
is the server source of truth (both must agree). The existing error table extends to
spot fields (`X not in refdata`, `required field missing or empty: X`,
`base_asset and quote_asset must differ`, `base × price must equal quote`). On submit
failure the same client_request_id is reused on retry (idempotent dedupe).

## Testing

- **Server `tests/test_draft_db.py`:** valid SPOT payload passes
  `validate_payload_for_category`; malformed SPOT (same-asset, missing price, bad
  direction) rejected; `draft_approve` routes SPOT → spot insert (mocked cursor).
- **Server `spot_insert` refactor regression:** `_insert_one(cur, payload)` returns the
  inserted row (mocked cursor); `main()` still produces the same stdout envelope as
  before (parse-stdin + validate + attachments path unchanged).
- **Plugin `tests/test_tokka_mo.py`:** `validate_spot_payload` happy path + each failure
  mode; `book-batch` with a mixed CASHFLOW+SPOT body; swap → LONG/base/quote mapping;
  `base × price == quote` tolerance.
- **Lint:** `scripts/lint_python.sh` strict flake8 (no one-liner defs, no aligned `=`,
  single space after commas).

## Shipping

1. `python scripts/update_version.py` + chore commit (required to ship).
2. Commit on a feature branch (not main); open PR per repo convention.
3. After merge + publish, users update via `claude plugin update tokka-mo@tokka-mo-marketplace`.

## Risks / call-outs

- **`spot_insert._insert_one` does not exist yet** — it must be extracted from
  `main()` first (see refactor above). After extraction it must keep `main()`'s
  stdin/attachment behavior intact (the React form and the existing `/api/spot/insert`
  path still call `main()`).
- **Account-optional SPOT** is intentional (matches server). Tighten only if the desk
  wants every spot row to carry an account.
- **Two diverging copies** is avoided here because no React form edit is needed; if a
  later change does touch `TradeBookingForm.jsx`, both copies must be edited.
