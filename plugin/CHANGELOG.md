# Changelog — tokka-mo plugin

Plugin-specific release notes. Versioned independently of the server.

## [Unreleased]

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
