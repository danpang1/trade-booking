# Changelog — tokka-mo plugin

Plugin-specific release notes. Versioned independently of the server.

## [Unreleased]

## [0.5.0] — 2026-09-30
### Added
- **TRANSFER bookings.** `book --category TRANSFER` / `book-batch` accept the
  transfer shape (one row, both ends on it: `source_*` / `dest_*`, signed
  `amount`, `initiated_datetime`, `network`, `ext_transfer_id`). INTERNAL =
  both ends ours (the server books the INCOMING mirror on the receiver);
  EXTERNAL = one end a refdata counterparty. The local validator mirrors
  `transfer_db`: sign follows direction, own ends must be refdata accounts
  with a `*_product` wherever the account offers one, the far end a refdata
  counterparty, same account both ends only across two products.
- `trade-booking` skill: a "TRANSFER specifics" section and
  `references/transfer-schema.md`. A movement between accounts is a transfer,
  never a cashflow: it changes where a position sits, not P&L.
### Changed
- `counterparty` guidance: exact refdata name only; the server rejects free
  text and stamps the CID itself (0.4.2).

## [0.4.0] — 2026-09-25
### Added
- `product` (the gateway sub-account) is now a mandatory booking field wherever
  the account offers a choice. The trade's `account_id` is derived from
  `account` + `product`, so a booking without one files the trade against the
  venue but not the sub-account, and the position and fee feeds cannot line it
  up.
- Resolved without asking where the answer is not a guess: the user named it;
  the account offers exactly one; a WALLET booking with a `network` (the
  network IS the chain); or a SPOT trade, taking the first of
  `SPOT` > `UNIFIED` > `DERIVATIVES`. Anything else is a question.
- `refdata_account` / `product_options` / `default_product` / `validate_product`
  in the CLI, so the skill and the Colossus bot share one rule rather than two
  drifting copies.

### Notes
- A CASHFLOW on a multi-product account is never defaulted — a funding fee and
  a spot settlement belong to different sub-accounts.
- Nor is an account offering only `FUNDING` / `TRADING` / `FUTURES` (the OKX and
  KuCoin accounts). `TRADING` shares gateway code `001` with `SPOT`, which makes
  it look like the obvious pick, but it is a distinct product and choosing it
  silently would mis-file the trade.
- Brokers, banks, and accounts refdata lists no options for are unaffected.

## [0.3.0] — 2026-09-01
### Added
- `loan-booking` skill: how MLA (the facility) and MCF (the cashflow that
  settles against it) relate, which case a request is in, and how to tag one
  to the other.
- `tokka-mo loan-list` — read-only lookup of loan agreements, so a cashflow is
  tagged to the right MLA instead of a guessed ref. Defaults to `--status LIVE`
  because only a live loan can be mapped to.
- `tokka-mo loan-open` — create a master loan agreement. **This is not a
  draft**: the server exposes only a direct `/api/loan/insert`, so the loan is
  live the moment it returns. Requires `--yes`; `--dry-run` validates and sends
  nothing.
- Local loan validation against cached refdata (portfolio id/name agreement,
  counterparty, both assets, enums, positive principal). `counterparty` is
  required here even though the server's own validator does not enforce it — a
  facility naming nobody cannot be reconciled or repaired later.

### Notes
- Cashflows are tagged to loans through `_meta.loan_deal_refs` on the existing
  CASHFLOW payload. No new booking path: `_meta` is carried through the draft
  untouched and the mapping is written in the same transaction as the cashflow.
- Mapping type is derived server-side: `LOAN` → `PRINCIPAL_DISBURSE`,
  `LOAN REPAYMENT` → `PRINCIPAL_REPAY`, `INTEREST EXPENSE`/`INTEREST INCOME` →
  `INTEREST`.

## [0.2.2] — 2026-08-28
### Fixed
- **`counterparty` is mandatory for SPOT**, not optional. 0.2.1 told the skill it
  was "genuinely optional for SPOT", so bookings came back saying "counterparty
  omitted". That came from reading the web form's `*` markers with a grep that
  only caught literal `required` props — Counterparty uses
  `required={form.category === "LOAN"}`, a dynamic prop, and was missed. Every
  SPOT trade has a party on the other side; if the user hasn't named one, ask.

## [0.2.1] — 2026-08-28
### Changed
- **Mandatory fields are now asked for, never defaulted.** The skill lists the
  exact `*` set the MO web form validates (`validate()` + `<Field required>` in
  `TradeBookingForm.jsx`) and must stop and ask when one is missing. The API is
  more permissive than the form, so a draft that the API accepts but that misses
  a `*` field cannot be opened or approved and strands in PENDING_REVIEW.
- **`account` is mandatory for SPOT.** Previously documented as optional because
  `spot_db` doesn't require it — but the form marks Account Name `*`, so an
  account-less SPOT draft was unapprovable. `counterparty` stays optional for
  SPOT.
- **Dropped the `TOKKA TREASURY` counterparty fallback** for OPEX vendors that
  aren't in refdata. It misattributed spend; the skill now asks instead.

### Fixed
- Version bumped so the pinned plugin cache actually refreshes. 0.2.0 shipped
  twice: `MARGIN LOAN` / `MARGIN REPAYMENT` were added to the CLI without a
  version change, so installs kept serving the older `VALID_CASHFLOW_TYPES` and
  rejected both types.

## [0.2.0] — 2026-06-30
### Added
- **SPOT / FX trade booking.** `tokka-mo book --category SPOT` and per-row
  `category` in `book-batch` now create SPOT drafts. New `validate_spot_payload`
  mirrors the server's `spot_db` rules plus refdata checks (portfolio, base/quote/
  fee assets, optional account/counterparty).
- `trade-booking` skill now parses SPOT and swap phrasing ("swap A to B @ price";
  received asset = base, LONG) and handles mixed CASHFLOW+SPOT batches in a single
  submission. New `references/spot-schema.md`.
- Server: un-stubbed SPOT in `draft_db.validate_payload_for_category` and routed
  SPOT approvals through `spot_insert._insert_one` (extracted from `main()`).

### Changed
- Renamed `/book` slash command to `/trade-booking` so the slash menu shows it as `/tokka-mo:trade-booking`, consistent with `/tokka-mo:login` and `/tokka-mo:drafts`.
- `book` / `book-batch` are now category-aware (CASHFLOW or SPOT); category is
  inferred from the payload when not given. CASHFLOW behavior is unchanged.

## [0.1.0] — 2026-05-26
### Added
- Initial plugin scaffold inside `middle-office-tools/plugin/`
- `tokka-mo` CLI: `login`, `logout`, `whoami`, `refdata refresh`, `book`, `book-batch`, `drafts list`
- `trade-booking` skill for Claude Code (CASHFLOW only)
- Slash commands: `/book`, `/drafts`, `/login`
- POSIX + Windows installers
