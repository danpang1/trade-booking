# Changelog — tokka-mo plugin

Plugin-specific release notes. Versioned independently of the server.

## [Unreleased]

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
