# Changelog — tokka-mo plugin

Plugin-specific release notes. Versioned independently of the server.

## [Unreleased]
### Changed
- Renamed `/book` slash command to `/trade-booking` so the slash menu shows it as `/tokka-mo:trade-booking`, consistent with `/tokka-mo:login` and `/tokka-mo:drafts`.

## [0.1.0] — 2026-05-26
### Added
- Initial plugin scaffold inside `middle-office-tools/plugin/`
- `tokka-mo` CLI: `login`, `logout`, `whoami`, `refdata refresh`, `book`, `book-batch`, `drafts list`
- `trade-booking` skill for Claude Code (CASHFLOW only)
- Slash commands: `/book`, `/drafts`, `/login`
- POSIX + Windows installers
