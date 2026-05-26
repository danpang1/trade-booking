# Claude Code Trade Booking — Phase 1b: `tokka-mo` Plugin (CASHFLOW v0.1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

---

**Goal:** Ship the standalone Claude Code plugin that lets any authenticated user submit CASHFLOW drafts in natural English from Claude Code. The plugin calls the Phase 1a `/api/bookings/draft(s)` endpoints; drafts land in the existing `<PendingDrafts>` inbox; the user reviews and approves there. **Single + batch, CASHFLOW only.** SPOT support and polish/rollout are deferred to Phase 2 / Phase 3.

**Architecture:** The plugin lives **inside the existing `middle-office-tools` repo** under `plugin/` — *not* a separate Bitbucket repo. This keeps server-side schema and the plugin's local validator in lockstep (one PR can update both) and skips the Bitbucket-admin bottleneck. Internal-only audience for v0.1; the plugin can be split into its own repo later if external distribution becomes a goal. One Python 3.10+ CLI (`plugin/bin/tokka-mo`, stdlib only — no external deps), a Claude Code skill in markdown (`plugin/skills/trade-booking/SKILL.md` + references), and three slash commands (`/book`, `/drafts`, `/login`). The CLI talks to the middle-office-tools server over HTTPS with Bearer auth; tokens are minted via a two-step login (`POST /api/auth/login` → session cookie → `POST /api/tokens` → token plaintext) and stored locally in `~/.config/tokka-mo/credentials` (`chmod 600`). Refdata (portfolios, accounts, counterparties, users, tokens) is cached at `~/.cache/tokka-mo/refdata.json` with a 24h TTL.

**Tech Stack:** Python 3.10+ (stdlib only — `urllib`, `json`, `argparse`, `getpass`, `pathlib`, `hashlib`, `subprocess`, `os`, `sys`), Markdown for skill + slash commands, Bash for installer, `.bat` shim for Windows. Pytest for the CLI's pure-logic tests.

**Reference:** [Design doc](../design/2026-05-23-claude-code-trade-booking-design.md) Section 7 (Claude Code plugin). Phase 1a plan: [`2026-05-25-claude-code-trade-booking-phase-1a-server-ui.md`](./2026-05-25-claude-code-trade-booking-phase-1a-server-ui.md). Phase 0 plan: [`2026-05-23-claude-code-trade-booking-phase-0.md`](./2026-05-23-claude-code-trade-booking-phase-0.md).

---

## Prerequisites (must be true BEFORE Task 1)

1. **`middle-office-tools` cloned locally** with write access. Working tree clean, on a fresh branch off `main` (or `feature/phase-1a-drafts` if Phase 1a hasn't merged yet). Run: `cd ~/Projects/middle-office-tools && git checkout -b feature/phase-1b-plugin main` (substitute the right base).
2. **Phase 1a deployed to UAT.** Confirmed by `curl https://mo-tools-uat.tokkalabs.com/api/health` returning `200`. (Already done as of 2026-05-26.)
3. **Claude Code installed locally.** `claude --version` works. The plugin loads at `~/.claude/plugins/tokka-mo/` (a symlink into the MO repo's `plugin/` subdir, set up by Task 14's `install.sh`).
4. **A test user with a UAT login** — used in Task 4's smoke. Don't use a shared service account.

---

## File Structure

**Created (all inside `middle-office-tools/plugin/`, 14 files):**

- `plugin/.claude-plugin/plugin.json` — Claude Code plugin manifest (name, version, skills, commands)
- `plugin/skills/trade-booking/SKILL.md` — the skill markdown (workflow, validation contract)
- `plugin/skills/trade-booking/references/cashflow-schema.md` — CASHFLOW field reference (the 14 required fields, enum sets, validation rules)
- `plugin/skills/trade-booking/references/examples.md` — worked examples (single + batch, INCOMING/OUTGOING, edge cases)
- `plugin/commands/book.md` — `/book` slash command sugar
- `plugin/commands/drafts.md` — `/drafts` slash command sugar
- `plugin/commands/login.md` — `/login` slash command sugar
- `plugin/bin/tokka-mo` — Python 3.10+ single-file CLI (the entire plugin runtime)
- `plugin/bin/tokka-mo.bat` — Windows shim that calls `py -3 %~dp0\tokka-mo %*`
- `plugin/tests/test_tokka_mo.py` — pure-logic pytest suite (no HTTP, no filesystem deps)
- `plugin/install.sh` — POSIX installer (symlinks `plugin/` into `~/.claude/plugins/tokka-mo`, registers CLI on PATH)
- `plugin/install.bat` — Windows installer
- `plugin/smoke.sh` — end-to-end smoke against UAT
- `plugin/README.md` — install + usage docs

**Modified (1):**

- `middle-office-tools/CHANGELOG.md` (if one exists) — append a Phase 1b note. If no CHANGELOG, create `plugin/CHANGELOG.md` for plugin-specific release notes (versioned independently of the server).

**Plan itself (separate, not a plugin source file):**

- `docs/plans/2026-05-26-claude-code-trade-booking-phase-1b-plugin.md`

**Untouched (explicitly):**

- All Phase 1a server-side scripts, endpoints, schema. The plugin is a pure client.
- `trades_cashflow`, `trades_spot`, `bookings_draft`, `api_tokens`, `users`, `sessions` schemas. No changes.
- `TradeBookingForm.jsx`, `PendingDrafts.jsx`, `server.js`. The plugin runs entirely on the user's laptop.

---

## Canonical paths used in this plan

| Symbol | Mac / Linux | Windows equivalent |
|---|---|---|
| `$REPO` | `~/Projects/middle-office-tools` | `%USERPROFILE%\Projects\middle-office-tools` (or wherever the MO repo is cloned) |
| `$PLUGIN_DIR` | `$REPO/plugin` (the subdir created by Task 1) | `%REPO%\plugin` |
| `$PLUGIN` | `~/.claude/plugins/tokka-mo` (symlinked to `$PLUGIN_DIR` by install.sh) | `%USERPROFILE%\.claude\plugins\tokka-mo` |
| `$CREDS` | `~/.config/tokka-mo/credentials` | `%APPDATA%\tokka-mo\credentials` |
| `$CACHE` | `~/.cache/tokka-mo/refdata.json` | `%LOCALAPPDATA%\tokka-mo\refdata.json` |
| `$UAT_URL` | `https://mo-tools-uat.tokkalabs.com` | same |
| `$PROD_URL` | `https://mo-tools.tokkalabs.com` | same |

---

## Task 1: Create the `plugin/` subdirectory + plugin manifest

**Goal:** Add a `plugin/` subdirectory inside `middle-office-tools` with the Claude Code plugin manifest, a plugin-local `.gitignore`, a stub README, and a `CHANGELOG.md` (versioned independently of the server). First plugin commit on the feature branch.

**Files:**
- Create: `$PLUGIN_DIR/.claude-plugin/plugin.json`
- Create: `$PLUGIN_DIR/.gitignore` (plugin-local; merges with the root MO `.gitignore`)
- Create: `$PLUGIN_DIR/README.md`
- Create: `$PLUGIN_DIR/CHANGELOG.md`

**Acceptance Criteria:**
- [ ] `cd $REPO && git log --oneline plugin/` shows one commit titled `chore(plugin): initial scaffold`
- [ ] `cat plugin/.claude-plugin/plugin.json` is valid JSON and includes `name`, `version`, `description`
- [ ] Plugin-local `.gitignore` excludes `__pycache__/`, `.pytest_cache/`, `*.pyc`, and (defence-in-depth) any local `credentials`/`refdata.json`
- [ ] No `LICENSE` file inside `plugin/` — the repo-root `LICENSE` already covers everything

**Verify:** `python -c "import json; print(json.load(open('plugin/.claude-plugin/plugin.json'))['version'])"` → `0.1.0`

**Steps:**

- [ ] **Step 1: Create the directory tree inside the existing MO repo**

```bash
cd ~/Projects/middle-office-tools
mkdir -p plugin/.claude-plugin
mkdir -p plugin/skills/trade-booking/references
mkdir -p plugin/commands
mkdir -p plugin/bin
mkdir -p plugin/tests
```

(No `git init` — we're already in a git repo. Make sure you're on a feature branch off `main`/`feature/phase-1a-drafts`: `git checkout -b feature/phase-1b-plugin`.)

- [ ] **Step 2: Write `plugin/.claude-plugin/plugin.json`**

```json
{
  "$schema": "https://docs.anthropic.com/claude-code/plugin.schema.json",
  "name": "tokka-mo",
  "version": "0.1.0",
  "description": "Submit Tokka Labs Middle Office trade bookings (CASHFLOW v0.1) as drafts from Claude Code. Approve in mo-tools.tokkalabs.com.",
  "author": "Tokka Labs Middle Office",
  "skills": [
    "skills/trade-booking"
  ],
  "commands": [
    "commands/book.md",
    "commands/drafts.md",
    "commands/login.md"
  ]
}
```

- [ ] **Step 3: Write `plugin/.gitignore`**

```
__pycache__/
*.pyc
.pytest_cache/
dist/
build/

# Defence-in-depth: these should NEVER live in the repo,
# but block them in case a user accidentally copies them in.
credentials
refdata.json
.tokka-mo/
```

- [ ] **Step 4: Write `plugin/README.md` (stub — full content lands in Task 14)**

```markdown
# tokka-mo — Claude Code plugin for Tokka Labs Middle Office

Submit CASHFLOW trade bookings as drafts from Claude Code, approve in the Middle Office web app.

This plugin lives **inside `middle-office-tools`** under `plugin/`. It is installed by symlinking `plugin/` into `~/.claude/plugins/tokka-mo` (see `install.sh`).

**Status:** v0.1 — CASHFLOW only. SPOT and polish coming in Phase 2 / Phase 3.
```

- [ ] **Step 5: Write `plugin/CHANGELOG.md`**

```markdown
# Changelog — tokka-mo plugin

Plugin-specific release notes. Versioned independently of the server.

## [Unreleased]

## [0.1.0] — 2026-05-26
### Added
- Initial plugin scaffold inside `middle-office-tools/plugin/`
- `tokka-mo` CLI: `login`, `logout`, `whoami`, `refdata refresh`, `book`, `book-batch`, `drafts list`
- `trade-booking` skill for Claude Code (CASHFLOW only)
- Slash commands: `/book`, `/drafts`, `/login`
- POSIX + Windows installers
```

- [ ] **Step 6: First commit**

```bash
git add plugin/.claude-plugin/plugin.json plugin/.gitignore plugin/README.md plugin/CHANGELOG.md
git commit -m "chore(plugin): initial scaffold"
```

---

## Task 2: CLI scaffolding (entrypoint + subcommand dispatch + version)

**Goal:** Wire the `tokka-mo` script as a runnable Python file with a subcommand argparse skeleton. No real commands yet — just `tokka-mo --version` and the `tokka-mo --help` tree.

**Files:**
- Create: `$REPO/bin/tokka-mo`
- Create: `$REPO/bin/tokka-mo.bat`

**Acceptance Criteria:**
- [ ] `bin/tokka-mo --version` prints `tokka-mo 0.1.0`
- [ ] `bin/tokka-mo --help` lists `login`, `logout`, `whoami`, `refdata`, `book`, `book-batch`, `drafts`
- [ ] `bin/tokka-mo book --help` shows usage (file: `-` for stdin)
- [ ] `bin/tokka-mo.bat --version` (on Windows) prints the same

**Verify:** `chmod +x bin/tokka-mo && bin/tokka-mo --version` → `tokka-mo 0.1.0`

**Steps:**

- [ ] **Step 1: Write `bin/tokka-mo`**

```python
#!/usr/bin/env python3
"""tokka-mo — Tokka Labs Middle Office CLI for Claude Code.

This single-file CLI is invoked by:
  • Claude Code's `trade-booking` skill (shell-out)
  • The user directly: `tokka-mo book < payload.json`
  • The slash commands /book /drafts /login

It has no external dependencies — Python 3.10+ stdlib only — so the install
is `chmod +x bin/tokka-mo` and a PATH symlink. No virtualenv, no pip.

Commands:
  login                 interactive login → mints API token → saves locally
  logout                revoke current token, clear local credentials
  whoami                show the authenticated user
  refdata refresh       pull /refdata/*.json + /tokens.json → local cache
  book < payload.json   POST one CASHFLOW draft
  book-batch < batch.json  POST N CASHFLOW drafts atomically
  drafts list [--status STATUS] [--batch BATCH_ID]  list your drafts
"""
from __future__ import annotations
import argparse
import json
import os
import sys

VERSION = "0.1.0"


def _cmd_not_implemented(name):
    def handler(args):
        print(f"tokka-mo: '{name}' not yet implemented", file=sys.stderr)
        return 99
    return handler


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tokka-mo",
        description="Tokka Labs Middle Office CLI for Claude Code.",
    )
    p.add_argument("--version", action="version", version=f"tokka-mo {VERSION}")
    p.add_argument(
        "--api-url",
        default=os.environ.get("TOKKA_MO_API_URL"),
        help=(
            "Base URL of the MO server (e.g. https://mo-tools.tokkalabs.com). "
            "Default: $TOKKA_MO_API_URL, or the saved value from `tokka-mo login`."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # login
    sp = sub.add_parser("login", help="Interactive login → mint API token → save")
    sp.add_argument("--api-url", dest="login_api_url", default=None,
                    help="Server base URL to save with the credentials")
    sp.add_argument(
        "--non-interactive", action="store_true",
        help="Read username and password from stdin (two lines). For CI / smoke.",
    )
    sp.set_defaults(func=_cmd_not_implemented("login"))

    # logout
    sp = sub.add_parser("logout", help="Revoke current token and clear local creds")
    sp.set_defaults(func=_cmd_not_implemented("logout"))

    # whoami
    sp = sub.add_parser("whoami", help="Show the authenticated user")
    sp.set_defaults(func=_cmd_not_implemented("whoami"))

    # refdata refresh
    sp = sub.add_parser("refdata", help="Manage local refdata cache")
    refdata_sub = sp.add_subparsers(dest="refdata_cmd", required=True)
    rsp = refdata_sub.add_parser("refresh", help="Pull /refdata/*.json into the cache")
    rsp.set_defaults(func=_cmd_not_implemented("refdata refresh"))

    # book (single)
    sp = sub.add_parser(
        "book",
        help="POST one CASHFLOW draft. JSON payload on stdin.",
    )
    sp.add_argument("--client-request-id", default=None,
                    help="Idempotency UUID. Auto-generated if omitted.")
    sp.set_defaults(func=_cmd_not_implemented("book"))

    # book-batch (atomic N)
    sp = sub.add_parser(
        "book-batch",
        help="POST N CASHFLOW drafts atomically. JSON on stdin: {trades: [...]}",
    )
    sp.set_defaults(func=_cmd_not_implemented("book-batch"))

    # drafts list
    sp = sub.add_parser("drafts", help="Inspect your drafts")
    drafts_sub = sp.add_subparsers(dest="drafts_cmd", required=True)
    dlp = drafts_sub.add_parser("list", help="List your drafts (text table)")
    dlp.add_argument("--status", choices=("PENDING_REVIEW", "APPROVED", "REJECTED"),
                     default=None)
    dlp.add_argument("--batch", dest="batch_id", default=None,
                     help="Filter to a single batch_id (UUID)")
    dlp.set_defaults(func=_cmd_not_implemented("drafts list"))

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Make the CLI executable**

```bash
chmod +x bin/tokka-mo
```

- [ ] **Step 3: Smoke**

```bash
bin/tokka-mo --version
```
Expected: `tokka-mo 0.1.0`

```bash
bin/tokka-mo --help
```
Expected: usage listing the seven subcommands.

```bash
bin/tokka-mo book --help
```
Expected: shows `--client-request-id` option.

- [ ] **Step 4: Write `bin/tokka-mo.bat` (Windows shim)**

```batch
@echo off
REM Windows shim for the tokka-mo CLI. Requires "py -3" or "python".
REM Forwards all arguments to the Python script in the same directory.
where py >NUL 2>&1
if %ERRORLEVEL% EQU 0 (
  py -3 "%~dp0tokka-mo" %*
) else (
  python "%~dp0tokka-mo" %*
)
```

- [ ] **Step 5: Commit**

```bash
git add bin/tokka-mo bin/tokka-mo.bat
git commit -m "feat(cli): scaffold tokka-mo entrypoint and Windows shim"
```

---

## Task 3: Credential storage helpers (TDD)

**Goal:** Read/write/clear local credentials at `$CREDS` with `chmod 600`. Pure-logic helpers exercised by pytest without touching the user's real config dir (override via `TOKKA_MO_CONFIG_DIR`).

**Files:**
- Modify: `$REPO/bin/tokka-mo` (add helpers, no command wiring yet)
- Create: `$REPO/tests/test_tokka_mo.py`

**Acceptance Criteria:**
- [ ] `save_credentials({api_url, username, token, prefix, token_id, expires_at})` writes a JSON file at `$CREDS` with mode `0o600`
- [ ] `load_credentials()` round-trips that JSON
- [ ] `load_credentials()` raises `CredsMissing` if file does not exist
- [ ] `clear_credentials()` deletes the file; no error if already absent
- [ ] All four behaviors covered by tests in `tests/test_tokka_mo.py`
- [ ] `TOKKA_MO_CONFIG_DIR` env var overrides the default `~/.config/tokka-mo` (so tests are hermetic)

**Verify:** `python -m pytest tests/test_tokka_mo.py -v` → all PASS

**Steps:**

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tokka_mo.py`:

```python
"""Pure-logic tests for tokka-mo CLI. No HTTP. Hermetic filesystem via tmp_path."""
import importlib.util
import json
import os
import sys
import stat
from pathlib import Path

import pytest


# Load the CLI from bin/tokka-mo (it has no .py extension, so we use importlib).
ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("tokka_mo", ROOT / "bin" / "tokka-mo")
tokka_mo = importlib.util.module_from_spec(SPEC)
sys.modules["tokka_mo"] = tokka_mo
SPEC.loader.exec_module(tokka_mo)


@pytest.fixture
def hermetic_config(tmp_path, monkeypatch):
    """Redirect $CREDS / $CACHE to a tmp dir so tests don't touch real config."""
    monkeypatch.setenv("TOKKA_MO_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("TOKKA_MO_CACHE_DIR", str(tmp_path / "cache"))
    return tmp_path


# ── Credential storage ─────────────────────────────────────────────

def test_load_credentials_missing_raises(hermetic_config):
    with pytest.raises(tokka_mo.CredsMissing):
        tokka_mo.load_credentials()


def test_save_then_load_round_trip(hermetic_config):
    creds = {
        "api_url": "https://mo-tools-uat.tokkalabs.com",
        "username": "alice",
        "token": "tkmo_abc123",
        "prefix": "tkmo_abc1",
        "token_id": 42,
        "expires_at": "2026-08-23T00:00:00+00:00",
    }
    tokka_mo.save_credentials(creds)
    loaded = tokka_mo.load_credentials()
    assert loaded == creds


def test_save_credentials_chmod_600(hermetic_config):
    # Skip on Windows — chmod semantics differ
    if os.name == "nt":
        pytest.skip("POSIX-only chmod check")
    tokka_mo.save_credentials({
        "api_url": "x", "username": "y", "token": "z",
        "prefix": "p", "token_id": 1, "expires_at": "t",
    })
    path = Path(os.environ["TOKKA_MO_CONFIG_DIR"]) / "credentials"
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_clear_credentials_removes_file(hermetic_config):
    tokka_mo.save_credentials({
        "api_url": "x", "username": "y", "token": "z",
        "prefix": "p", "token_id": 1, "expires_at": "t",
    })
    tokka_mo.clear_credentials()
    with pytest.raises(tokka_mo.CredsMissing):
        tokka_mo.load_credentials()


def test_clear_credentials_idempotent_when_absent(hermetic_config):
    # Should NOT raise even if file never existed.
    tokka_mo.clear_credentials()
```

- [ ] **Step 2: Run tests, watch them fail**

```bash
python -m pytest tests/test_tokka_mo.py -v
```
Expected: tests fail with `AttributeError: module 'tokka_mo' has no attribute 'CredsMissing'` (etc).

- [ ] **Step 3: Add credential helpers to `bin/tokka-mo`**

Insert after the `VERSION = "0.1.0"` line:

```python
# ─────────────────────────────────────────────────────────────────
# Credential storage — JSON file at $CREDS, chmod 600.
#
# Override via $TOKKA_MO_CONFIG_DIR for hermetic tests.
# ─────────────────────────────────────────────────────────────────


class CredsMissing(FileNotFoundError):
    """Raised when load_credentials() can't find a credentials file."""


def _config_dir():
    override = os.environ.get("TOKKA_MO_CONFIG_DIR")
    if override:
        return os.path.expanduser(override)
    if os.name == "nt":
        return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "tokka-mo")
    return os.path.expanduser("~/.config/tokka-mo")


def _creds_path():
    return os.path.join(_config_dir(), "credentials")


def save_credentials(creds: dict) -> None:
    """Write {api_url, username, token, prefix, token_id, expires_at} as JSON.
    Created with mode 0o600 on POSIX. Parents are created with 0o700.
    """
    d = _config_dir()
    os.makedirs(d, exist_ok=True)
    if os.name != "nt":
        os.chmod(d, 0o700)
    p = _creds_path()
    # Write to a temp path then rename, so an interrupted write can't
    # leave a half-formed credentials file.
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(creds, f, indent=2, sort_keys=True)
    if os.name != "nt":
        os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def load_credentials() -> dict:
    p = _creds_path()
    if not os.path.exists(p):
        raise CredsMissing(f"no credentials at {p}; run: tokka-mo login")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def clear_credentials() -> None:
    p = _creds_path()
    try:
        os.remove(p)
    except FileNotFoundError:
        pass
```

- [ ] **Step 4: Run tests, watch them pass**

```bash
python -m pytest tests/test_tokka_mo.py -v
```
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add bin/tokka-mo tests/test_tokka_mo.py
git commit -m "feat(cli): add credential storage helpers + tests"
```

---

## Task 4: `tokka-mo login` — interactive two-step login → mint token → save

**Goal:** Prompt for username + password (hidden), POST `/api/auth/login` to get a session cookie, POST `/api/tokens` with that cookie to mint a long-lived Bearer token, save the token locally, log out the session cookie.

**Files:**
- Modify: `$REPO/bin/tokka-mo` (HTTP helpers + `login` command)

**Acceptance Criteria:**
- [ ] `bin/tokka-mo --api-url https://mo-tools-uat.tokkalabs.com login` prompts for username/password, prints `Logged in as <user>. Token expires <date>.`, and saves `$CREDS` with mode 0o600
- [ ] Wrong password prints `Login failed: invalid credentials` and exits non-zero. No file written.
- [ ] After success, `cat $CREDS` shows a JSON file containing `api_url`, `username`, `token` (`tkmo_` prefix), `prefix`, `token_id`, `expires_at`
- [ ] If a credentials file already exists, login prints `Replacing existing credentials for <username>...` and overwrites it
- [ ] If `--api-url` is omitted AND `$TOKKA_MO_API_URL` is unset AND no creds exist, login prints a clear error and exits

**Verify:** Smoke against UAT (Step 4 below)

**Steps:**

- [ ] **Step 1: Add HTTP helpers**

In `bin/tokka-mo`, after the credential helpers, add:

```python
# ─────────────────────────────────────────────────────────────────
# HTTP helpers — stdlib urllib only.
#
# Two helpers:
#   _http_json(url, ...)   — generic JSON POST/GET/DELETE, returns
#                            (status, body_or_dict, response_headers).
#   resolve_api_url(args)  — order: --api-url, $TOKKA_MO_API_URL,
#                            saved creds.api_url, else error.
# ─────────────────────────────────────────────────────────────────
import urllib.request
import urllib.error


def resolve_api_url(args) -> str:
    """Return the server base URL, raise on missing."""
    candidates = []
    if getattr(args, "login_api_url", None):
        candidates.append(args.login_api_url)
    if getattr(args, "api_url", None):
        candidates.append(args.api_url)
    if not candidates:
        try:
            candidates.append(load_credentials().get("api_url"))
        except CredsMissing:
            pass
    for c in candidates:
        if c:
            return c.rstrip("/")
    raise SystemExit(
        "tokka-mo: no API URL set. Use --api-url, $TOKKA_MO_API_URL, "
        "or run `tokka-mo login --api-url <url>` first."
    )


def _http_json(method: str, url: str, *, body=None, headers=None, timeout=10):
    """Send a JSON request. Returns (status, parsed_body_or_text, response_headers)."""
    data = None
    h = {"Accept": "application/json"}
    if headers:
        h.update(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            try:
                parsed = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                parsed = raw
            return resp.status, parsed, dict(resp.getheaders())
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = raw
        return e.code, parsed, dict(e.headers or {})
    except urllib.error.URLError as e:
        raise SystemExit(f"tokka-mo: cannot reach {url}: {e.reason}")
```

- [ ] **Step 2: Implement the `login` handler**

Add (anywhere above `build_parser`):

```python
# ─────────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────────
import getpass


def cmd_login(args) -> int:
    """Two-step login:
      1. POST /api/auth/login → Set-Cookie: sid=<session>
      2. POST /api/tokens with that cookie → token plaintext (returned ONCE)
      3. Save token; discard cookie (we never use cookies again for this CLI).
    """
    api_url = resolve_api_url(args)
    if getattr(args, "non_interactive", False):
        # CI / smoke path: read two lines from stdin (username, password)
        username = sys.stdin.readline().rstrip("\r\n")
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        username = input("Username: ").strip()
        if not username:
            print("login aborted: empty username", file=sys.stderr)
            return 2
        password = getpass.getpass("Password: ")
    if not username or not password:
        print("login aborted: empty username or password", file=sys.stderr)
        return 2

    # Step 1: cookie login
    status, body, headers = _http_json(
        "POST", f"{api_url}/api/auth/login",
        body={"username": username, "password": password},
    )
    if status != 200 or not (isinstance(body, dict) and body.get("ok")):
        msg = (isinstance(body, dict) and body.get("error")) or f"HTTP {status}"
        print(f"Login failed: {msg}", file=sys.stderr)
        return 3
    set_cookie = headers.get("Set-Cookie", "") or headers.get("set-cookie", "")
    sid = _extract_sid(set_cookie)
    if not sid:
        print("Login failed: server did not return a session cookie", file=sys.stderr)
        return 3

    # Step 2: mint a long-lived API token
    token_name = f"tokka-mo CLI ({_hostname()})"
    status, body, _ = _http_json(
        "POST", f"{api_url}/api/tokens",
        body={"name": token_name, "expires_in_days": 90},
        headers={"Cookie": f"sid={sid}"},
    )
    if status != 200 or not (isinstance(body, dict) and body.get("ok")):
        msg = (isinstance(body, dict) and body.get("error")) or f"HTTP {status}"
        print(f"Token mint failed: {msg}", file=sys.stderr)
        return 4
    token = body.get("token")
    prefix = body.get("prefix")
    token_id = body.get("id")
    expires_at = body.get("expires_at")
    if not token:
        print("Token mint failed: server did not return a token plaintext", file=sys.stderr)
        return 4

    # Step 3: save; we never need the session cookie again. The server
    # cleans up idle sessions, so no explicit logout is required for the
    # cookie. (Bearer tokens are separately revocable via `tokka-mo logout`.)
    save_credentials({
        "api_url": api_url,
        "username": username,
        "token": token,
        "prefix": prefix,
        "token_id": token_id,
        "expires_at": expires_at,
    })
    print(f"Logged in as {username}. Token {prefix}… expires {expires_at}.")
    return 0


def _extract_sid(set_cookie_header: str) -> str | None:
    """Parse 'sid=abc; HttpOnly; ...' → 'abc'. Empty string → None."""
    if not set_cookie_header:
        return None
    for part in set_cookie_header.split(";"):
        part = part.strip()
        if part.startswith("sid="):
            v = part[4:]
            return v or None
    return None


def _hostname() -> str:
    import socket
    try:
        return socket.gethostname()
    except Exception:
        return "unknown-host"
```

- [ ] **Step 3: Wire the handler in `build_parser`**

Replace the `sp.set_defaults(func=_cmd_not_implemented("login"))` line for `login` with:

```python
    sp.set_defaults(func=cmd_login)
```

- [ ] **Step 4: Smoke against UAT** (use your real UAT credentials)

```bash
bin/tokka-mo --api-url https://mo-tools-uat.tokkalabs.com login
```
Expected:
```
Username: <type your username>
Password: <type, hidden>
Logged in as <username>. Token tkmo_xxxx… expires 2026-08-24T00:00:00+00:00.
```

Verify:
```bash
ls -l ~/.config/tokka-mo/
# expect: drwx------ ... credentials  (mode 700 dir)
cat ~/.config/tokka-mo/credentials
# expect: pretty JSON with api_url, username, token (tkmo_…), prefix, token_id, expires_at
stat -f '%Sp' ~/.config/tokka-mo/credentials   # mac: -rw-------
# OR
stat -c '%a' ~/.config/tokka-mo/credentials    # linux: 600
```

Negative path:
```bash
bin/tokka-mo --api-url https://mo-tools-uat.tokkalabs.com login
# type a bad password
# expect: "Login failed: invalid credentials" exit 3, no file written
```

- [ ] **Step 5: Add a unit test for `_extract_sid`**

Append to `tests/test_tokka_mo.py`:

```python
# ── _extract_sid parser ─────────────────────────────────────────

def test_extract_sid_basic():
    h = "sid=abc123; HttpOnly; SameSite=Lax; Path=/; Max-Age=43200"
    assert tokka_mo._extract_sid(h) == "abc123"


def test_extract_sid_missing():
    assert tokka_mo._extract_sid("") is None
    assert tokka_mo._extract_sid("Other=foo") is None


def test_extract_sid_empty_value():
    # Logout-style cookie: sid=
    assert tokka_mo._extract_sid("sid=; Max-Age=0") is None
```

Run: `python -m pytest tests/test_tokka_mo.py -v` → all PASS.

- [ ] **Step 6: Commit**

```bash
git add bin/tokka-mo tests/test_tokka_mo.py
git commit -m "feat(cli): tokka-mo login — two-step credential mint"
```

---

## Task 5: `tokka-mo whoami` and `tokka-mo logout`

**Goal:** Read-after-login sanity (`whoami`) and clean revoke (`logout`).

**Files:**
- Modify: `$REPO/bin/tokka-mo`

**Acceptance Criteria:**
- [ ] `tokka-mo whoami` prints `username · role · token tkmo_xxxx… (expires DATE)` on success
- [ ] `tokka-mo whoami` with no creds prints `not logged in; run: tokka-mo login` and exits 4
- [ ] `tokka-mo whoami` with expired/revoked token prints `Token rejected — run: tokka-mo login` and exits 4
- [ ] `tokka-mo logout` DELETEs the token via `/api/tokens/:id`, removes the local creds file, prints `Logged out.`
- [ ] `tokka-mo logout` with no creds prints `not logged in` and exits 0 (idempotent)

**Verify:** Smoke in Step 4

**Steps:**

- [ ] **Step 1: Add a small `_authed_request` helper that injects the Bearer header**

After `_http_json`:

```python
def _authed_request(method: str, path: str, *, body=None, timeout=10):
    """Send an authenticated request using the saved creds.
    Returns (status, parsed_body, response_headers). On 401 we surface
    a clear hint to re-login.
    """
    creds = load_credentials()
    url = creds["api_url"].rstrip("/") + path
    headers = {"Authorization": f"Bearer {creds['token']}"}
    return _http_json(method, url, body=body, headers=headers, timeout=timeout)
```

- [ ] **Step 2: Implement `cmd_whoami`**

```python
def cmd_whoami(args) -> int:
    try:
        creds = load_credentials()
    except CredsMissing:
        print("not logged in; run: tokka-mo login", file=sys.stderr)
        return 4
    status, body, _ = _authed_request("GET", "/api/auth/me")
    if status == 401:
        print("Token rejected — run: tokka-mo login", file=sys.stderr)
        return 4
    if status != 200 or not (isinstance(body, dict) and body.get("ok")):
        msg = (isinstance(body, dict) and body.get("error")) or f"HTTP {status}"
        print(f"whoami failed: {msg}", file=sys.stderr)
        return 5
    user = body.get("user") or {}
    print(
        f"{user.get('username','?')} · {user.get('role','?')} · "
        f"token {creds['prefix']}… (expires {creds['expires_at']})"
    )
    return 0
```

- [ ] **Step 3: Implement `cmd_logout`**

```python
def cmd_logout(args) -> int:
    try:
        creds = load_credentials()
    except CredsMissing:
        print("not logged in", file=sys.stderr)
        return 0
    token_id = creds.get("token_id")
    if token_id is not None:
        status, body, _ = _authed_request("DELETE", f"/api/tokens/{token_id}")
        # 204 (no content) is the success path; 401/404 also acceptable
        # (token already revoked or expired). We always clear local creds.
        if status not in (200, 204, 401, 404):
            msg = (isinstance(body, dict) and body.get("error")) or f"HTTP {status}"
            print(f"logout: server returned {msg}; clearing local creds anyway",
                  file=sys.stderr)
    clear_credentials()
    print("Logged out.")
    return 0
```

- [ ] **Step 4: Wire both handlers**

In `build_parser`, change the `set_defaults` lines for `whoami` and `logout`:

```python
    sp.set_defaults(func=cmd_whoami)
    # ...and...
    sp.set_defaults(func=cmd_logout)
```

- [ ] **Step 5: Smoke**

```bash
bin/tokka-mo whoami
# expect: <you> · trader · token tkmo_xxxx… (expires 2026-08-24...)

bin/tokka-mo logout
# expect: Logged out.

bin/tokka-mo whoami
# expect: not logged in; run: tokka-mo login   (exit 4)
```

Re-login for downstream tasks:
```bash
bin/tokka-mo --api-url https://mo-tools-uat.tokkalabs.com login
```

- [ ] **Step 6: Commit**

```bash
git add bin/tokka-mo
git commit -m "feat(cli): tokka-mo whoami + logout"
```

---

## Task 6: Refdata cache helpers (TDD)

**Goal:** Pull and cache `/refdata/portfolios.json`, `/refdata/accounts.json`, `/refdata/counterparties.json`, `/refdata/users.json`, and `/tokens.json` into a single `$CACHE` file (`refdata.json`) with a `fetched_at` timestamp. Helpers expose `load_refdata(force_refresh=False)` that refreshes if older than 24h.

**Files:**
- Modify: `$REPO/bin/tokka-mo`
- Modify: `$REPO/tests/test_tokka_mo.py`

**Acceptance Criteria:**
- [ ] `fetch_refdata(api_url, token)` downloads all 5 files and returns a single dict
- [ ] `save_refdata_cache(data)` writes to `$CACHE` with a `fetched_at` ISO string
- [ ] `load_refdata(force_refresh=False)` returns the cached dict if fresh, otherwise refreshes
- [ ] `is_cache_fresh(cache, now)` returns False if `fetched_at` is older than 24h or missing
- [ ] Tests cover stale → refresh, fresh → no-op, and missing-file → refresh paths (using `monkeypatch` to fake the HTTP calls)

**Verify:** `python -m pytest tests/test_tokka_mo.py -v` → all PASS

**Steps:**

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tokka_mo.py`:

```python
# ── Refdata cache ──────────────────────────────────────────────

def test_is_cache_fresh_returns_true_within_24h(hermetic_config):
    import datetime as dt
    cache = {"fetched_at": dt.datetime(2026, 5, 25, 12, 0, 0, tzinfo=dt.timezone.utc).isoformat()}
    now = dt.datetime(2026, 5, 25, 23, 0, 0, tzinfo=dt.timezone.utc)
    assert tokka_mo.is_cache_fresh(cache, now=now) is True


def test_is_cache_fresh_returns_false_after_24h(hermetic_config):
    import datetime as dt
    cache = {"fetched_at": dt.datetime(2026, 5, 24, 12, 0, 0, tzinfo=dt.timezone.utc).isoformat()}
    now = dt.datetime(2026, 5, 25, 13, 0, 0, tzinfo=dt.timezone.utc)  # 25h later
    assert tokka_mo.is_cache_fresh(cache, now=now) is False


def test_is_cache_fresh_handles_missing_field(hermetic_config):
    assert tokka_mo.is_cache_fresh({}, now=None) is False
    assert tokka_mo.is_cache_fresh({"fetched_at": ""}, now=None) is False
    assert tokka_mo.is_cache_fresh({"fetched_at": "not-a-date"}, now=None) is False


def test_save_and_reload_refdata_cache(hermetic_config):
    data = {
        "fetched_at": "2026-05-25T12:00:00+00:00",
        "portfolios": [{"id": 8006, "name": "CDA"}],
        "accounts": [{"id": 1, "name": "BINANCE TK006"}],
        "counterparties": [{"id": 1, "name": "Galaxy"}],
        "users": [{"id": 1, "name": "danny.pang"}],
        "tokens": [{"symbol": "USDC"}],
    }
    tokka_mo.save_refdata_cache(data)
    loaded = tokka_mo.load_refdata_cache()
    assert loaded == data


def test_load_refdata_cache_returns_none_when_missing(hermetic_config):
    assert tokka_mo.load_refdata_cache() is None
```

Run: `pytest tests/test_tokka_mo.py -v` — these 5 should FAIL.

- [ ] **Step 2: Implement cache helpers**

In `bin/tokka-mo`, after credentials helpers:

```python
# ─────────────────────────────────────────────────────────────────
# Refdata cache — single JSON file at $CACHE.
# Schema: {fetched_at, portfolios, accounts, counterparties, users, tokens}
# ─────────────────────────────────────────────────────────────────
import datetime as _dt


def _cache_dir():
    override = os.environ.get("TOKKA_MO_CACHE_DIR")
    if override:
        return os.path.expanduser(override)
    if os.name == "nt":
        return os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "tokka-mo"
        )
    return os.path.expanduser("~/.cache/tokka-mo")


def _cache_path():
    return os.path.join(_cache_dir(), "refdata.json")


def save_refdata_cache(data: dict) -> None:
    d = _cache_dir()
    os.makedirs(d, exist_ok=True)
    p = _cache_path()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp, p)


def load_refdata_cache() -> dict | None:
    p = _cache_path()
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def is_cache_fresh(cache: dict, *, now=None) -> bool:
    """True if cache.fetched_at is within the last 24h."""
    if not cache or not isinstance(cache, dict):
        return False
    fetched_at = cache.get("fetched_at")
    if not fetched_at or not isinstance(fetched_at, str):
        return False
    try:
        # Python 3.11+ tolerates 'Z'; we explicitly normalize.
        ts = _dt.datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=_dt.timezone.utc)
    now = now or _dt.datetime.now(_dt.timezone.utc)
    return (now - ts) < _dt.timedelta(hours=24)


def fetch_refdata(api_url: str, token: str) -> dict:
    """Download all 5 refdata sources. Returns the merged dict (no fetched_at —
    that's stamped by save_refdata_cache's caller below).
    """
    api_url = api_url.rstrip("/")
    headers = {"Authorization": f"Bearer {token}"}
    out = {}
    sources = {
        "portfolios": "/refdata/portfolios.json",
        "accounts": "/refdata/accounts.json",
        "counterparties": "/refdata/counterparties.json",
        "users": "/refdata/users.json",
        "tokens": "/tokens.json",
    }
    for key, path in sources.items():
        status, body, _ = _http_json("GET", api_url + path, headers=headers)
        if status != 200:
            raise SystemExit(
                f"tokka-mo: refdata fetch failed for {path} "
                f"(HTTP {status}); try `tokka-mo login` if expired"
            )
        out[key] = body
    return out


def load_refdata(*, force_refresh: bool = False) -> dict:
    """Return the refdata dict, refreshing from server if stale or missing."""
    cache = load_refdata_cache()
    if cache and not force_refresh and is_cache_fresh(cache):
        return cache
    creds = load_credentials()
    fresh = fetch_refdata(creds["api_url"], creds["token"])
    fresh["fetched_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
    save_refdata_cache(fresh)
    return fresh
```

- [ ] **Step 3: Run tests, watch them pass**

```bash
python -m pytest tests/test_tokka_mo.py -v
```
Expected: all (≥10) tests PASS.

- [ ] **Step 4: Commit**

```bash
git add bin/tokka-mo tests/test_tokka_mo.py
git commit -m "feat(cli): refdata cache helpers + tests"
```

---

## Task 7: `tokka-mo refdata refresh`

**Goal:** Wire the cache helpers to the `refdata refresh` subcommand.

**Files:**
- Modify: `$REPO/bin/tokka-mo`

**Acceptance Criteria:**
- [ ] `tokka-mo refdata refresh` prints a brief summary (`portfolios: N · accounts: N · counterparties: N · users: N · tokens: N · fetched <time>`)
- [ ] After running, `cat $CACHE` contains 5 keys + `fetched_at`
- [ ] With no creds: prints `not logged in; run: tokka-mo login` and exits 4

**Verify:** Smoke in Step 2

**Steps:**

- [ ] **Step 1: Implement `cmd_refdata_refresh`**

```python
def cmd_refdata_refresh(args) -> int:
    try:
        load_credentials()
    except CredsMissing:
        print("not logged in; run: tokka-mo login", file=sys.stderr)
        return 4
    data = load_refdata(force_refresh=True)
    print(
        f"portfolios: {len(data.get('portfolios') or [])} · "
        f"accounts: {len(data.get('accounts') or [])} · "
        f"counterparties: {len(data.get('counterparties') or [])} · "
        f"users: {len(data.get('users') or [])} · "
        f"tokens: {len(data.get('tokens') or [])} · "
        f"fetched {data['fetched_at']}"
    )
    return 0
```

Wire it: `rsp.set_defaults(func=cmd_refdata_refresh)`.

- [ ] **Step 2: Smoke**

```bash
bin/tokka-mo refdata refresh
# expect: portfolios: 12 · accounts: 80 · counterparties: 50 · ... · fetched 2026-05-26T...
```

- [ ] **Step 3: Commit**

```bash
git add bin/tokka-mo
git commit -m "feat(cli): tokka-mo refdata refresh"
```

---

## Task 8: CASHFLOW payload validator (TDD)

**Goal:** Pure-logic `validate_cashflow_payload(payload, refdata)` that mirrors the server's `cashflow_db.validate_payload` rules:

- All 14 required fields present and non-empty:
  `cashflow_type, direction, entity, portfolio_id, portfolio_name, counterparty, account, account_type, asset, amount, trade_date, value_date, user_id, status`
- `direction in {INCOMING, OUTGOING}`
- `status in {PENDING, CONFIRMED, PROCESSED, SETTLED, CANCELLED}`
- `account_type in {EXCHANGE, WALLET, BROKER}`
- `cashflow_type in VALID_CASHFLOW_TYPES` (11 values, see below)
- `network` (if present) in the uppercase set from `src/data/networks.js`
- `abs(float(amount)) > 0`
- `trade_date`, `value_date` parse as ISO 8601 with timezone
- `portfolio_id` is one of the IDs in `refdata.portfolios`
- `portfolio_name` matches that portfolio
- `counterparty` is one of the names in `refdata.counterparties`
- `account` is one of the names in `refdata.accounts`
- `asset` is one of the symbols in `refdata.tokens`

The plugin can fail fast and not waste a server round-trip if the user has a stale refdata cache and a typo'd value.

**Files:**
- Modify: `$REPO/bin/tokka-mo`
- Modify: `$REPO/tests/test_tokka_mo.py`

**Acceptance Criteria:**
- [ ] A complete valid payload passes (no raise)
- [ ] Missing each required field raises `ValidationError` naming the field
- [ ] Bad enums raise `ValidationError` naming the value + valid set
- [ ] `amount=0` raises
- [ ] `portfolio_id` not in refdata raises with hint listing 3 nearest matches
- [ ] All other refdata-bound fields likewise

**Verify:** `pytest tests/test_tokka_mo.py -v` all PASS

**Steps:**

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tokka_mo.py`:

```python
# ── CASHFLOW payload validator ──────────────────────────────────

REFDATA_FIXTURE = {
    "portfolios": [
        {"id": 8006, "name": "CDA"},
        {"id": 8041, "name": "MARKET MAKING"},
    ],
    "accounts": [
        {"name": "TK006@BINANCE"},
        {"name": "TK818@BINANCE"},
        {"name": "TOKKA TREASURY WALLET"},
    ],
    "counterparties": [
        {"name": "Galaxy"},
        {"name": "TOKKA TREASURY"},
        {"name": "TOKKA LABS PTE LTD"},
    ],
    "tokens": [
        {"symbol": "USDC"},
        {"symbol": "USDT"},
        {"symbol": "BEBOP"},
    ],
    "users": [{"username": "danny.pang"}],
    "fetched_at": "2026-05-26T00:00:00+00:00",
}

VALID_PAYLOAD = {
    "cashflow_type": "OPEX",
    "direction": "OUTGOING",
    "entity": "TOKKA LABS PTE LTD",
    "portfolio_id": 8006,
    "portfolio_name": "CDA",
    "counterparty": "TOKKA TREASURY",
    "account": "TOKKA TREASURY WALLET",
    "account_type": "WALLET",
    "asset": "USDC",
    "amount": "888",
    "trade_date": "2026-05-26T12:00:00+00:00",
    "value_date": "2026-05-26T12:00:00+00:00",
    "user_id": "danny.pang",
    "status": "PENDING",
}


def test_validate_cashflow_payload_happy_path():
    tokka_mo.validate_cashflow_payload(VALID_PAYLOAD, REFDATA_FIXTURE)


@pytest.mark.parametrize("field", [
    "cashflow_type", "direction", "entity", "portfolio_id", "portfolio_name",
    "counterparty", "account", "account_type", "asset", "amount",
    "trade_date", "value_date", "user_id", "status",
])
def test_validate_missing_required_field_raises(field):
    bad = {k: v for k, v in VALID_PAYLOAD.items() if k != field}
    with pytest.raises(tokka_mo.ValidationError, match=field):
        tokka_mo.validate_cashflow_payload(bad, REFDATA_FIXTURE)


def test_validate_bad_direction():
    bad = {**VALID_PAYLOAD, "direction": "IN"}
    with pytest.raises(tokka_mo.ValidationError, match="direction"):
        tokka_mo.validate_cashflow_payload(bad, REFDATA_FIXTURE)


def test_validate_bad_account_type():
    bad = {**VALID_PAYLOAD, "account_type": "POCKET"}
    with pytest.raises(tokka_mo.ValidationError, match="account_type"):
        tokka_mo.validate_cashflow_payload(bad, REFDATA_FIXTURE)


def test_validate_zero_amount():
    bad = {**VALID_PAYLOAD, "amount": "0"}
    with pytest.raises(tokka_mo.ValidationError, match="amount"):
        tokka_mo.validate_cashflow_payload(bad, REFDATA_FIXTURE)


def test_validate_portfolio_not_in_refdata():
    bad = {**VALID_PAYLOAD, "portfolio_id": 9999}
    with pytest.raises(tokka_mo.ValidationError, match="portfolio_id"):
        tokka_mo.validate_cashflow_payload(bad, REFDATA_FIXTURE)


def test_validate_counterparty_not_in_refdata():
    bad = {**VALID_PAYLOAD, "counterparty": "TOTALLY MADE UP CO"}
    with pytest.raises(tokka_mo.ValidationError, match="counterparty"):
        tokka_mo.validate_cashflow_payload(bad, REFDATA_FIXTURE)


def test_validate_asset_not_in_refdata():
    bad = {**VALID_PAYLOAD, "asset": "DOGECOIN"}
    with pytest.raises(tokka_mo.ValidationError, match="asset"):
        tokka_mo.validate_cashflow_payload(bad, REFDATA_FIXTURE)
```

Run: tests FAIL with `AttributeError: module 'tokka_mo' has no attribute 'validate_cashflow_payload'`.

- [ ] **Step 2: Implement the validator**

In `bin/tokka-mo`, after the refdata helpers:

```python
# ─────────────────────────────────────────────────────────────────
# CASHFLOW payload validation — mirrors scripts/cashflow_db.py on
# the server, plus refdata-bound enum checks using the local cache.
# ─────────────────────────────────────────────────────────────────


class ValidationError(ValueError):
    """Raised by validate_cashflow_payload for any malformed input."""


REQUIRED_CASHFLOW_FIELDS = (
    "cashflow_type", "direction", "entity", "portfolio_id",
    "portfolio_name", "counterparty", "account", "account_type",
    "asset", "amount", "trade_date", "value_date", "user_id", "status",
)
VALID_DIRECTIONS = {"INCOMING", "OUTGOING"}
VALID_STATUSES = {"PENDING", "CONFIRMED", "PROCESSED", "SETTLED", "CANCELLED"}
VALID_ACCOUNT_TYPES = {"EXCHANGE", "WALLET", "BROKER"}
VALID_CASHFLOW_TYPES = {
    "INTER PTF FUNDING", "RETAINER FEES", "OPEX",
    "OTHER INCOME", "OTHER EXPENSE", "TRANSFER FEES",
    "INTEREST EXPENSE", "INTEREST INCOME", "WITHHOLDING TAX",
    "LOAN", "LOAN REPAYMENT",
}


def _refdata_values(refdata: dict, key: str, name_field: str = "name") -> set:
    """Pull a set of names/symbols from a refdata list. Defensive about shapes."""
    items = refdata.get(key) or []
    out = set()
    for item in items:
        if isinstance(item, dict):
            v = item.get(name_field)
            if v:
                out.add(v)
        elif isinstance(item, str):
            out.add(item)
    return out


def _refdata_portfolio_ids(refdata: dict) -> dict:
    """{id: name} so we can validate id + name match together."""
    out = {}
    for p in refdata.get("portfolios") or []:
        if isinstance(p, dict) and "id" in p and "name" in p:
            out[p["id"]] = p["name"]
    return out


def _suggest(value, choices, n=3):
    """Return n closest choices as a string hint."""
    import difflib
    if not choices:
        return ""
    matches = difflib.get_close_matches(str(value), [str(c) for c in choices], n=n, cutoff=0.0)
    return f" Did you mean: {', '.join(matches)}?" if matches else ""


def validate_cashflow_payload(payload: dict, refdata: dict) -> None:
    """Raise ValidationError on any rule break. Otherwise return None."""
    if not isinstance(payload, dict):
        raise ValidationError("payload must be an object")

    for field in REQUIRED_CASHFLOW_FIELDS:
        v = payload.get(field)
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValidationError(f"required field missing or empty: {field}")

    # Enum checks
    if payload["direction"] not in VALID_DIRECTIONS:
        raise ValidationError(
            f"direction must be one of {sorted(VALID_DIRECTIONS)}, got {payload['direction']!r}"
        )
    if payload["status"] not in VALID_STATUSES:
        raise ValidationError(
            f"status must be one of {sorted(VALID_STATUSES)}, got {payload['status']!r}"
        )
    if payload["account_type"] not in VALID_ACCOUNT_TYPES:
        raise ValidationError(
            f"account_type must be one of {sorted(VALID_ACCOUNT_TYPES)}, got {payload['account_type']!r}"
        )
    if payload["cashflow_type"] not in VALID_CASHFLOW_TYPES:
        raise ValidationError(
            f"cashflow_type must be one of {sorted(VALID_CASHFLOW_TYPES)}, "
            f"got {payload['cashflow_type']!r}"
        )

    # Amount
    try:
        amt = float(str(payload["amount"]))
    except (TypeError, ValueError):
        raise ValidationError(f"amount must be numeric, got {payload['amount']!r}")
    if abs(amt) == 0:
        raise ValidationError("amount must be non-zero")

    # Dates
    for d in ("trade_date", "value_date"):
        try:
            _dt.datetime.fromisoformat(payload[d].replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            raise ValidationError(
                f"{d} must be ISO 8601 with timezone, got {payload[d]!r}"
            )

    # Refdata-bound fields
    ports = _refdata_portfolio_ids(refdata)
    if payload["portfolio_id"] not in ports:
        suggest = _suggest(payload["portfolio_id"], sorted(ports.keys()))
        raise ValidationError(
            f"portfolio_id {payload['portfolio_id']!r} not in refdata.{suggest} "
            f"Run `tokka-mo refdata refresh` if your cache is stale."
        )
    expected_name = ports[payload["portfolio_id"]]
    if payload["portfolio_name"] != expected_name:
        raise ValidationError(
            f"portfolio_name {payload['portfolio_name']!r} doesn't match "
            f"portfolio_id {payload['portfolio_id']} (expected {expected_name!r})"
        )

    counterparties = _refdata_values(refdata, "counterparties")
    if payload["counterparty"] not in counterparties:
        raise ValidationError(
            f"counterparty {payload['counterparty']!r} not in refdata."
            f"{_suggest(payload['counterparty'], counterparties)}"
        )

    accounts = _refdata_values(refdata, "accounts")
    if payload["account"] not in accounts:
        raise ValidationError(
            f"account {payload['account']!r} not in refdata."
            f"{_suggest(payload['account'], accounts)}"
        )

    tokens = _refdata_values(refdata, "tokens", name_field="symbol")
    if payload["asset"] not in tokens:
        raise ValidationError(
            f"asset {payload['asset']!r} not in refdata."
            f"{_suggest(payload['asset'], tokens)}"
        )
```

- [ ] **Step 3: Run tests, watch them pass**

```bash
python -m pytest tests/test_tokka_mo.py -v
```
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add bin/tokka-mo tests/test_tokka_mo.py
git commit -m "feat(cli): CASHFLOW payload validator (mirrors cashflow_db rules)"
```

---

## Task 9: `tokka-mo book` — POST one CASHFLOW draft

**Goal:** Read a JSON payload from stdin, validate it locally, generate (or accept) a `client_request_id` UUID, POST to `/api/bookings/draft`, print the response (or error).

**Files:**
- Modify: `$REPO/bin/tokka-mo`

**Acceptance Criteria:**
- [ ] `cat payload.json | tokka-mo book` prints `Draft #N created (PENDING_REVIEW). Review at <api_url>/pending`
- [ ] On validation failure (locally): prints the error, exits 3, no HTTP call made
- [ ] On server validation failure: prints the server's error, exits 3
- [ ] Same `client_request_id` resubmitted: server returns `deduped: true`; CLI prints `Draft #N already existed (idempotent retry).`
- [ ] On 401: prints `Token rejected — run: tokka-mo login` exit 4
- [ ] `--client-request-id <uuid>` accepted; CLI fails fast if it's not a valid UUID

**Verify:** Smoke in Step 3

**Steps:**

- [ ] **Step 1: Implement `cmd_book`**

```python
import uuid as _uuid


def _read_stdin_json():
    raw = sys.stdin.read().strip()
    if not raw:
        raise SystemExit("tokka-mo: no JSON on stdin (use a heredoc or pipe a file)")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise SystemExit(f"tokka-mo: invalid JSON on stdin: {e}")


def cmd_book(args) -> int:
    payload = _read_stdin_json()

    # Idempotency key
    crid = args.client_request_id or str(_uuid.uuid4())
    try:
        _uuid.UUID(crid)
    except (ValueError, AttributeError):
        print(f"tokka-mo: --client-request-id {crid!r} is not a valid UUID", file=sys.stderr)
        return 3

    # Local validation against cached refdata
    try:
        refdata = load_refdata()
    except CredsMissing:
        print("not logged in; run: tokka-mo login", file=sys.stderr)
        return 4
    try:
        validate_cashflow_payload(payload, refdata)
    except ValidationError as e:
        print(f"validation failed: {e}", file=sys.stderr)
        return 3

    # POST /api/bookings/draft
    status, body, _ = _authed_request(
        "POST", "/api/bookings/draft",
        body={
            "category": "CASHFLOW",
            "payload": payload,
            "client_request_id": crid,
        },
    )
    if status == 401:
        print("Token rejected — run: tokka-mo login", file=sys.stderr)
        return 4
    if status not in (200, 201) or not (isinstance(body, dict) and body.get("ok")):
        msg = (isinstance(body, dict) and body.get("error")) or f"HTTP {status}"
        print(f"server rejected draft: {msg}", file=sys.stderr)
        return 3
    row = body.get("row") or {}
    deduped = body.get("deduped", False)
    creds = load_credentials()
    review_url = f"{creds['api_url']}/pending"
    if deduped:
        print(f"Draft #{row.get('id')} already existed (idempotent retry). Review at {review_url}")
    else:
        print(f"Draft #{row.get('id')} created (PENDING_REVIEW). Review at {review_url}")
    return 0
```

Wire: in `build_parser`, change the `set_defaults` for `book` to `func=cmd_book`.

- [ ] **Step 2: Test against UAT**

Create a temp payload (replace `<your_username>`):

```bash
cat > /tmp/p.json <<EOF
{
  "cashflow_type": "OPEX",
  "direction": "OUTGOING",
  "entity": "TOKKA LABS PTE LTD",
  "portfolio_id": 8006,
  "portfolio_name": "CDA",
  "counterparty": "TOKKA TREASURY",
  "account": "TOKKA TREASURY WALLET",
  "account_type": "WALLET",
  "asset": "USDC",
  "amount": "1",
  "trade_date": "2026-05-26T12:00:00+00:00",
  "value_date": "2026-05-26T12:00:00+00:00",
  "user_id": "<your_username>",
  "status": "PENDING"
}
EOF

cat /tmp/p.json | bin/tokka-mo book
# expect: Draft #N created (PENDING_REVIEW). Review at https://mo-tools-uat.../pending
```

Test idempotency — capture the CRID from the previous and replay:

```bash
CRID=$(uuidgen | tr 'A-Z' 'a-z')
cat /tmp/p.json | bin/tokka-mo book --client-request-id $CRID
# Draft #M created (PENDING_REVIEW). ...
cat /tmp/p.json | bin/tokka-mo book --client-request-id $CRID
# Draft #M already existed (idempotent retry). ...
```

Test validation error (omit `cashflow_type`):

```bash
echo '{"direction":"OUTGOING"}' | bin/tokka-mo book
# expect: validation failed: required field missing or empty: cashflow_type, exit 3
```

- [ ] **Step 3: Cleanup** — reject the test drafts via the UI or with the next task.

- [ ] **Step 4: Commit**

```bash
git add bin/tokka-mo
git commit -m "feat(cli): tokka-mo book — single CASHFLOW draft"
```

---

## Task 10: `tokka-mo book-batch` — atomic N-row submit

**Goal:** Read `{trades: [...]}` from stdin where each trade has its own payload + optional `client_request_id`. Validate every trade locally before any HTTP call. POST the whole batch to `/api/bookings/draft/batch`. Report `batch_id` + per-row results.

**Files:**
- Modify: `$REPO/bin/tokka-mo`

**Acceptance Criteria:**
- [ ] Valid 3-row batch prints `Batch <uuid> · 3 drafts created (#A, #B, #C). Review at <url>/pending`
- [ ] If one trade fails local validation, no HTTP call is made and the row index + error is printed
- [ ] If the server rejects the batch (e.g. one trade has a server-only check fail), nothing is inserted (atomic) and the message is printed
- [ ] `client_request_id` per trade — auto-generated if omitted; CLI checks uniqueness within the batch
- [ ] `--max-batch-size 50` cap enforced client-side (server also caps)

**Verify:** Smoke in Step 2

**Steps:**

- [ ] **Step 1: Implement `cmd_book_batch`**

```python
def cmd_book_batch(args) -> int:
    body = _read_stdin_json()
    if not isinstance(body, dict) or not isinstance(body.get("trades"), list):
        print("tokka-mo: stdin must be {\"trades\": [...]}", file=sys.stderr)
        return 3
    trades = body["trades"]
    if not trades:
        print("tokka-mo: trades list is empty", file=sys.stderr)
        return 3
    if len(trades) > 50:
        print(f"tokka-mo: batch too large ({len(trades)} > 50)", file=sys.stderr)
        return 3

    # Load refdata once
    try:
        refdata = load_refdata()
    except CredsMissing:
        print("not logged in; run: tokka-mo login", file=sys.stderr)
        return 4

    # Local validation
    prepared = []
    seen_crids = set()
    for i, t in enumerate(trades):
        if not isinstance(t, dict):
            print(f"trade {i}: not an object", file=sys.stderr)
            return 3
        payload = t.get("payload") or t  # allow bare payloads, infer category
        crid = t.get("client_request_id") or str(_uuid.uuid4())
        try:
            _uuid.UUID(crid)
        except (ValueError, AttributeError):
            print(f"trade {i}: invalid client_request_id {crid!r}", file=sys.stderr)
            return 3
        if crid in seen_crids:
            print(f"trade {i}: duplicate client_request_id in batch: {crid}", file=sys.stderr)
            return 3
        seen_crids.add(crid)
        try:
            validate_cashflow_payload(payload, refdata)
        except ValidationError as e:
            print(f"trade {i} validation failed: {e}", file=sys.stderr)
            return 3
        prepared.append({
            "category": "CASHFLOW",
            "payload": payload,
            "client_request_id": crid,
        })

    # POST batch
    status, body, _ = _authed_request(
        "POST", "/api/bookings/draft/batch",
        body={"trades": prepared},
    )
    if status == 401:
        print("Token rejected — run: tokka-mo login", file=sys.stderr)
        return 4
    if status not in (200, 201) or not (isinstance(body, dict) and body.get("ok")):
        msg = (isinstance(body, dict) and body.get("error")) or f"HTTP {status}"
        print(f"server rejected batch: {msg}", file=sys.stderr)
        return 3
    batch_id = body.get("batch_id")
    rows = body.get("rows") or []
    ids = [str(r.get("id")) for r in rows]
    creds = load_credentials()
    print(
        f"Batch {batch_id} · {len(rows)} drafts created "
        f"(#{', #'.join(ids)}). Review at {creds['api_url']}/pending"
    )
    return 0
```

Wire: `func=cmd_book_batch` for the `book-batch` parser.

- [ ] **Step 2: Smoke against UAT** (3-row batch, all valid)

```bash
cat > /tmp/batch.json <<EOF
{
  "trades": [
    {"payload": $(cat /tmp/p.json)},
    {"payload": $(cat /tmp/p.json | jq '.amount="2"')},
    {"payload": $(cat /tmp/p.json | jq '.amount="3"')}
  ]
}
EOF
cat /tmp/batch.json | bin/tokka-mo book-batch
# expect: Batch <uuid> · 3 drafts created (#X, #Y, #Z). Review at ...
```

Negative path — one trade with bad amount=0:

```bash
echo '{"trades":[{"payload":'"$(cat /tmp/p.json)"'},{"payload":'"$(cat /tmp/p.json | jq '.amount="0"')"'}]}' \
  | bin/tokka-mo book-batch
# expect: trade 1 validation failed: amount must be non-zero, exit 3, no HTTP call
```

- [ ] **Step 3: Commit**

```bash
git add bin/tokka-mo
git commit -m "feat(cli): tokka-mo book-batch — atomic N-row CASHFLOW submit"
```

---

## Task 11: `tokka-mo drafts list`

**Goal:** GET `/api/bookings/drafts` (with optional `status` / `batch_id` filters), render as a compact text table.

**Files:**
- Modify: `$REPO/bin/tokka-mo`

**Acceptance Criteria:**
- [ ] `tokka-mo drafts list` shows all drafts (newest first) with columns `ID · STATUS · CATEGORY · CREATED · SUMMARY`
- [ ] `--status PENDING_REVIEW` filters
- [ ] `--batch <uuid>` filters
- [ ] Empty result prints `(no drafts)`
- [ ] On 401: re-login hint

**Verify:** Smoke in Step 2

**Steps:**

- [ ] **Step 1: Implement `cmd_drafts_list`**

```python
def _summarize_payload(p):
    """One-line cashflow summary for the text table."""
    if not isinstance(p, dict):
        return "(empty)"
    parts = [
        p.get("cashflow_type"), p.get("direction"),
        p.get("amount"), p.get("asset"),
        p.get("counterparty"), p.get("network"),
    ]
    return " · ".join(str(x) for x in parts if x)


def cmd_drafts_list(args) -> int:
    qs = []
    if args.status:
        qs.append(f"status={args.status}")
    if args.batch_id:
        qs.append(f"batch_id={args.batch_id}")
    path = "/api/bookings/drafts" + (("?" + "&".join(qs)) if qs else "")
    status, body, _ = _authed_request("GET", path)
    if status == 401:
        print("Token rejected — run: tokka-mo login", file=sys.stderr)
        return 4
    if status != 200 or not (isinstance(body, dict) and body.get("ok")):
        msg = (isinstance(body, dict) and body.get("error")) or f"HTTP {status}"
        print(f"list failed: {msg}", file=sys.stderr)
        return 5
    drafts = body.get("drafts") or []
    if not drafts:
        print("(no drafts)")
        return 0
    # Compact text table
    print(f"{'ID':>5}  {'STATUS':<14}  {'CAT':<8}  {'CREATED':<19}  SUMMARY")
    print("-" * 100)
    for d in drafts:
        created = (d.get("created_at") or "")[:19].replace("T", " ")
        print(
            f"{d.get('id'):>5}  "
            f"{(d.get('status') or '')[:14]:<14}  "
            f"{(d.get('category') or '')[:8]:<8}  "
            f"{created:<19}  "
            f"{_summarize_payload(d.get('payload'))}"
        )
    return 0
```

Wire: `func=cmd_drafts_list`.

- [ ] **Step 2: Smoke**

```bash
bin/tokka-mo drafts list
bin/tokka-mo drafts list --status PENDING_REVIEW
# After Task 10, batch UUID was printed:
bin/tokka-mo drafts list --batch <that-uuid>
```

- [ ] **Step 3: Commit**

```bash
git add bin/tokka-mo
git commit -m "feat(cli): tokka-mo drafts list (with status/batch filters)"
```

---

## Task 12: Skill — `skills/trade-booking/SKILL.md` + references

**Goal:** The skill markdown that activates when a user says "book a cashflow", `/book`, etc. It teaches Claude the validation contract and the workflow (parse → preview → require `y` → shell-out to `tokka-mo book` or `book-batch`).

**Files:**
- Create: `$REPO/skills/trade-booking/SKILL.md`
- Create: `$REPO/skills/trade-booking/references/cashflow-schema.md`
- Create: `$REPO/skills/trade-booking/references/examples.md`

**Acceptance Criteria:**
- [ ] `SKILL.md` has the standard plugin skill frontmatter (`name`, `description`) and an activation list
- [ ] The workflow lists 6 steps verbatim from the design doc
- [ ] `cashflow-schema.md` lists all 14 required fields with type, enum, and "where it comes from"
- [ ] `examples.md` shows 3 worked examples: (a) single OPEX, (b) 3-row batch, (c) edge case (missing field, what to ask)

**Verify:** Eyeball the markdown; no runtime test.

**Steps:**

- [ ] **Step 1: Write `skills/trade-booking/SKILL.md`**

````markdown
---
name: trade-booking
description: Submit Tokka Labs Middle Office CASHFLOW trade bookings as drafts. Activates when the user mentions booking a cashflow, OPEX, transfer, funding, or runs `/book`. Validates against live refdata, shows a structured preview, requires explicit `y` confirmation, then shells out to `tokka-mo`. Never makes HTTP calls itself. CASHFLOW only in v0.1 — SPOT is coming in Phase 2.
---

# Trade Booking — CASHFLOW (v0.1)

## When to activate

The user wants to book one or more CASHFLOW trades — they'll say things like:
- "book a $500K OPEX to TOKKA TREASURY"
- "submit these 6 cashflows from the Slack thread"
- "/book"
- "draft an OUTGOING transfer of 100 USDC to Galaxy"

If the user mentions a SPOT trade ("buy 10 BTC at 95k"), say: "SPOT support ships in Phase 2 — for now, please book SPOT trades through the Middle Office web form." Don't try to handle it.

## Hard rules

1. **You never make HTTP calls.** Everything goes through `tokka-mo` shell-outs. If `tokka-mo` isn't on the PATH, tell the user to run the install script.
2. **Show a structured preview AND get explicit `y` before submitting.** Never submit on first parse. Never assume.
3. **Validate against the local refdata cache (`tokka-mo refdata refresh` if stale).** If a value isn't in the live set, STOP and ask — don't guess at the closest match. See [[feedback_claude_plugin_validate_refdata]] in user memory.
4. **One `client_request_id` UUID per draft, generated by `tokka-mo`.** Don't manually mint one. If a submit fails and the user wants to retry, reuse the same CRID — see [[feedback_claude_plugin_retry_idempotency]].
5. **CASHFLOW-only.** If the trade isn't a cashflow, bail.

## Workflow

1. **Parse the user's input** into a list of CASHFLOW trades (1 or N). For each, extract: cashflow_type, direction, amount, asset, counterparty, account, network (if on-chain), entity, portfolio_id, value_date.
2. **Identify missing required fields** (see `references/cashflow-schema.md`). Ask the user to supply them — one round of questions, batched.
3. **Validate** against the cached refdata: portfolio_id, counterparty, account, asset. If anything's missing or wrong, ask the user (don't substitute).
4. **Show a structured preview** in a code block. For batches, number the rows.
5. **Ask: "Submit? (y/N)"** — wait for an explicit `y`. Anything else is a no.
6. **On `y`**: shell out to `tokka-mo book` (single) or `tokka-mo book-batch` (N≥2). Report draft IDs + the review URL.

## Common patterns

### OPEX payment
- cashflow_type: `OPEX`
- direction: `OUTGOING`
- counterparty: vendor name (must be in `tokka-mo refdata` — if not, fall back to `TOKKA TREASURY` and tell user it'll need a vendor add later)
- account_type: `WALLET` (chain) or `EXCHANGE` (CEX)
- asset: ticker (USDC, USDT, etc.)

### Inter-portfolio funding
- cashflow_type: `INTER PTF FUNDING`
- direction: `OUTGOING` from source ptf, `INCOMING` into dest ptf (book both)
- counterparty: target entity name

### Interest income / expense
- cashflow_type: `INTEREST INCOME` (or `INTEREST EXPENSE`)
- direction: `INCOMING` (or `OUTGOING`)
- counterparty: who's paying / being paid

## Field reference

See `references/cashflow-schema.md` for the full 14-field contract with enum sets.

## Worked examples

See `references/examples.md` for single + batch + edge-case examples.

## Errors you'll see

| Error | What it means | What to do |
|---|---|---|
| `not logged in` | Stale CLI session | Run `tokka-mo login` |
| `Token rejected — run: tokka-mo login` | 401 from server | Re-login |
| `required field missing or empty: X` | Validation gap | Ask user to supply X |
| `X not in refdata` | Stale cache or genuine typo | Run `tokka-mo refdata refresh`. If still missing, ask user. |
| `cannot reach <url>` | Network / VPN issue | Tell user; don't retry blindly. |
````

- [ ] **Step 2: Write `skills/trade-booking/references/cashflow-schema.md`**

````markdown
# CASHFLOW Schema (v0.1)

The 14 required fields a CASHFLOW draft must carry. The plugin's local validator AND the server's `cashflow_db.validate_payload` enforce the same rules — if one fails, the other will too.

| Field | Type | Notes |
|---|---|---|
| `cashflow_type` | enum | One of: `INTER PTF FUNDING`, `RETAINER FEES`, `OPEX`, `OTHER INCOME`, `OTHER EXPENSE`, `TRANSFER FEES`, `INTEREST EXPENSE`, `INTEREST INCOME`, `WITHHOLDING TAX`, `LOAN`, `LOAN REPAYMENT` |
| `direction` | enum | `INCOMING` or `OUTGOING` |
| `entity` | string | Legal entity. Common values: `TOKKA LABS PTE LTD`, `ECHO CREEK LIMITED`, `IMAGINE LABS PTE LTD`, `NATIVE TECHNOLOGY LIMITED`, `RANGE PROTOCOL LIMITED` |
| `portfolio_id` | int | Must match an `id` in `tokka-mo refdata` |
| `portfolio_name` | string | Must match the name of `portfolio_id`'s row in `tokka-mo refdata` |
| `counterparty` | string | Must match a `name` in `tokka-mo refdata`. Falls back to `TOKKA TREASURY` for OPEX where vendor isn't catalogued yet |
| `account` | string | Must match an `account` name in `tokka-mo refdata` (e.g. `TK006@BINANCE`) |
| `account_type` | enum | `EXCHANGE`, `WALLET`, or `BROKER` |
| `asset` | string | Must match a `symbol` in `tokka-mo refdata` (e.g. `USDC`) |
| `amount` | numeric string | Positive magnitude. Server derives signed amount from `direction` |
| `trade_date` | ISO 8601 + tz | When the booking is recorded (typically "now") |
| `value_date` | ISO 8601 + tz | When the value moves (typically "now" or T+1) |
| `user_id` | string | Set automatically by the plugin from the logged-in username |
| `status` | enum | `PENDING`, `CONFIRMED`, `PROCESSED`, `SETTLED`, `CANCELLED`. Default `PENDING` for drafts. |

## Optional fields

| Field | Type | Notes |
|---|---|---|
| `network` | enum | Uppercase chain name (`ETHEREUM`, `BASE`, `ARBITRUM`, ...). Required if `account_type=WALLET` |
| `tx_hash` | string | 0x-prefixed 64-hex if known. EVM networks only |
| `comment` | string | Free-text |

## Where values come from

- `portfolio_id` / `portfolio_name`: `refdata.portfolios`
- `counterparty`: `refdata.counterparties`
- `account`: `refdata.accounts`
- `asset`: `refdata.tokens`
- `user_id`: `tokka-mo whoami` (auto)
- `cashflow_type` / `direction` / `status` / `account_type`: enums in this doc — NOT from refdata

## Validation order

The plugin validates in this order (fail fast):
1. All 14 required fields non-empty
2. Enum membership
3. Amount non-zero, parses as float
4. Dates parse as ISO 8601 with timezone
5. Refdata-bound fields (portfolio, counterparty, account, asset) match cache

Both client and server validate. The client catches typos before a round-trip; the server is the source of truth.
````

- [ ] **Step 3: Write `skills/trade-booking/references/examples.md`**

````markdown
# Worked Examples

## Example 1 — Single OPEX

**User:** "book a 500 USDC OPEX payment to TOKKA TREASURY out of CDA"

**Skill behavior:**

1. Parse → `{cashflow_type: OPEX, direction: OUTGOING, amount: "500", asset: USDC, counterparty: TOKKA TREASURY, portfolio: CDA(8006)}`. Missing: `account`, `account_type`, `network`, `entity`.
2. Refdata lookup: `CDA` → `portfolio_id=8006`. Ask user: "Which account is this out of?" — present the chalk-list of accounts for portfolio 8006.
3. User answers: `TOKKA TREASURY WALLET` (chain: ETHEREUM).
4. Preview:

```
CASHFLOW · OPEX · OUTGOING
  amount:        500 USDC
  entity:        TOKKA LABS PTE LTD
  portfolio:     8006 (CDA)
  counterparty:  TOKKA TREASURY
  account:       TOKKA TREASURY WALLET (WALLET)
  network:       ETHEREUM
  value_date:    2026-05-26T12:00:00+00:00
```

5. Ask "Submit? (y/N)"; on `y`, shell out:

```bash
tokka-mo book <<'JSON'
{
  "cashflow_type": "OPEX",
  "direction": "OUTGOING",
  "entity": "TOKKA LABS PTE LTD",
  "portfolio_id": 8006,
  "portfolio_name": "CDA",
  "counterparty": "TOKKA TREASURY",
  "account": "TOKKA TREASURY WALLET",
  "account_type": "WALLET",
  "network": "ETHEREUM",
  "asset": "USDC",
  "amount": "500",
  "trade_date": "2026-05-26T12:00:00+00:00",
  "value_date": "2026-05-26T12:00:00+00:00",
  "user_id": "danny.pang",
  "status": "PENDING"
}
JSON
```

6. Report:
```
Draft #42 created (PENDING_REVIEW). Review at https://mo-tools.tokkalabs.com/pending
```

## Example 2 — 6-row batch from a Slack paste

**User pastes:**
```
funding in to 8006 from Galaxy: 100k USDC
funding in to 8006 from Galaxy: 200k USDC
funding in to 8006 from Galaxy: 50k USDT
OPEX outgoing from 8006: 10k USDC to OFFICE VENDOR
OPEX outgoing from 8006: 5k USDC to OFFICE VENDOR
INTEREST INCOME to 8006 from Galaxy: 2k USDC
```

**Skill behavior:**

1. Parse 6 cashflows. Identify `OFFICE VENDOR` isn't in refdata. **STOP and ask the user**: "OFFICE VENDOR isn't in counterparties. Should I use TOKKA TREASURY as a placeholder, or do you want to add OFFICE VENDOR first?"
2. User says: "Use TOKKA TREASURY for now."
3. Preview a 6-row table.
4. "Submit batch? (y/N)" — on `y`:

```bash
tokka-mo book-batch <<'JSON'
{"trades": [
  {"payload": {...row 1...}},
  {"payload": {...row 2...}},
  ...
]}
JSON
```

5. Report:
```
Batch a8b3-1234-... · 6 drafts created (#43, #44, #45, #46, #47, #48). Review at https://mo-tools.../pending
```

## Example 3 — Edge case: missing field

**User:** "book an outgoing transfer"

**Skill behavior:**

1. Identifies that direction=OUTGOING is the only thing known. cashflow_type, amount, asset, counterparty, portfolio, account all missing.
2. **Ask ONE round of batched questions** (not one at a time):
   > Need a few details to draft this:
   > - cashflow_type? (OPEX, TRANSFER FEES, INTER PTF FUNDING, ...)
   > - amount + asset? (e.g. "100 USDC")
   > - to whom? (counterparty)
   > - from which portfolio + account?
3. After answers, proceed to validation + preview as in Example 1.
````

- [ ] **Step 4: Commit**

```bash
git add skills/
git commit -m "feat(skill): trade-booking skill for CASHFLOW + references"
```

---

## Task 13: Slash commands — `/book`, `/drafts`, `/login`

**Goal:** Three thin markdown shims under `commands/` that surface the skill / CLI behind shorter triggers.

**Files:**
- Create: `$REPO/commands/book.md`
- Create: `$REPO/commands/drafts.md`
- Create: `$REPO/commands/login.md`

**Acceptance Criteria:**
- [ ] Each file has Claude Code slash-command frontmatter (`description`)
- [ ] `/book` invokes the `trade-booking` skill (no special args)
- [ ] `/drafts` calls `tokka-mo drafts list` and renders the table
- [ ] `/login` calls `tokka-mo login`

**Steps:**

- [ ] **Step 1: Write `commands/book.md`**

````markdown
---
description: Start a CASHFLOW trade booking flow (single or batch). Invokes the trade-booking skill.
---

Activate the **trade-booking** skill for this turn.

If the user has already typed natural-language booking instructions after `/book`, treat those as the source. Otherwise, ask:

> What would you like to book? (e.g. "500 USDC OPEX out of CDA to TOKKA TREASURY", or paste a multi-line list for a batch)

Then follow the skill's workflow: parse → ask for missing fields → preview → require `y` → shell out to `tokka-mo book` (single) or `tokka-mo book-batch` (multi).
````

- [ ] **Step 2: Write `commands/drafts.md`**

````markdown
---
description: List your pending CASHFLOW drafts. Optional --status / --batch filters.
---

Run:

```bash
tokka-mo drafts list
```

Then render the output as a clean Markdown table. If the user added arguments (e.g. `/drafts --status PENDING_REVIEW`), pass them through:

```bash
tokka-mo drafts list --status PENDING_REVIEW
```

If `tokka-mo` prints `not logged in`, suggest: "Run `/login` first."

After listing, remind the user that approve/reject happens in the Middle Office web app at `<api_url>/pending` — the CLI is for submission only in v0.1.
````

- [ ] **Step 3: Write `commands/login.md`**

````markdown
---
description: One-time setup — log in to the Middle Office server and mint a long-lived API token.
---

Run:

```bash
tokka-mo login --api-url https://mo-tools.tokkalabs.com
```

The CLI will prompt for username and password (the password is hidden as you type). On success it saves a 90-day Bearer token at `~/.config/tokka-mo/credentials` (chmod 600).

For UAT testing, use `--api-url https://mo-tools-uat.tokkalabs.com`.

After login, verify with:

```bash
tokka-mo whoami
```
````

- [ ] **Step 4: Commit**

```bash
git add commands/
git commit -m "feat(commands): /book /drafts /login slash commands"
```

---

## Task 14: Installer + README

**Goal:** `install.sh` (POSIX) and `install.bat` (Windows) — symlink `$PLUGIN_DIR` into `~/.claude/plugins/tokka-mo`, put `bin/tokka-mo` on the PATH; a full README with install, first-time setup, troubleshooting.

**Files:**
- Create: `$PLUGIN_DIR/install.sh`
- Create: `$PLUGIN_DIR/install.bat`
- Modify: `$PLUGIN_DIR/README.md` (full content)

**Acceptance Criteria:**
- [ ] `cd plugin && ./install.sh` from a fresh clone symlinks `plugin/` into `~/.claude/plugins/tokka-mo`, makes `bin/tokka-mo` executable, ensures `~/.config/tokka-mo` and `~/.cache/tokka-mo` exist, prints a clear "next: run /login in Claude Code" message
- [ ] `install.bat` does the equivalent for Windows
- [ ] `README.md` covers: prerequisites, install one-liner, first-time login, sanity check, common workflow, troubleshooting

**Steps:**

- [ ] **Step 1: Write `install.sh`**

```bash
#!/usr/bin/env bash
# tokka-mo Claude Code plugin installer (macOS / Linux).
# Run from inside the plugin directory:
#   cd <middle-office-tools>/plugin && ./install.sh
#
# Idempotent. Safe to re-run after `git pull` to update.

set -euo pipefail

PLUGIN_SRC="$(cd "$(dirname "$0")" && pwd)"      # …/middle-office-tools/plugin
PLUGIN_DIR="${HOME}/.claude/plugins/tokka-mo"
BIN_LINK="${HOME}/.local/bin/tokka-mo"

echo "tokka-mo installer"
echo "  source: ${PLUGIN_SRC}"

# Verify Python 3.10+
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found on PATH. Install Python 3.10+ first." >&2
  exit 1
fi
PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info[0])')
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info[1])')
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
  echo "ERROR: tokka-mo requires Python 3.10+. Found $PY_MAJOR.$PY_MINOR." >&2
  exit 1
fi

# Register plugin: symlink the plugin/ subdir into ~/.claude/plugins/tokka-mo
mkdir -p "$(dirname "$PLUGIN_DIR")"
if [ -L "$PLUGIN_DIR" ] || [ -d "$PLUGIN_DIR" ]; then
  rm -rf "$PLUGIN_DIR"
fi
ln -s "$PLUGIN_SRC" "$PLUGIN_DIR"
echo "  ✓ linked plugin to ${PLUGIN_DIR}"

# Make CLI executable
chmod +x "${PLUGIN_SRC}/bin/tokka-mo"

# Symlink CLI into ~/.local/bin for PATH access
mkdir -p "$(dirname "$BIN_LINK")"
ln -sf "${PLUGIN_SRC}/bin/tokka-mo" "$BIN_LINK"
echo "  ✓ linked CLI to ${BIN_LINK}"

# Ensure config + cache dirs exist
mkdir -p "${HOME}/.config/tokka-mo" "${HOME}/.cache/tokka-mo"
chmod 700 "${HOME}/.config/tokka-mo"
echo "  ✓ created ${HOME}/.config/tokka-mo (chmod 700) and ${HOME}/.cache/tokka-mo"

# PATH hint
case ":${PATH}:" in
  *":${HOME}/.local/bin:"*) ;;
  *) echo
     echo "NOTE: ${HOME}/.local/bin is not in your PATH."
     echo "Add this to your shell rc (~/.zshrc or ~/.bashrc):"
     echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
     ;;
esac

echo
echo "Done. Next steps:"
echo "  1. Open Claude Code"
echo "  2. Run: /login  (or: tokka-mo login --api-url https://mo-tools.tokkalabs.com)"
echo "  3. Sanity:    tokka-mo whoami"
echo "  4. Book:      /book"
```

```bash
chmod +x install.sh
```

- [ ] **Step 2: Write `install.bat`**

```batch
@echo off
REM tokka-mo Claude Code plugin installer (Windows).
REM Run from inside the plugin directory:
REM   cd <middle-office-tools>\plugin
REM   install.bat

setlocal EnableExtensions

set "PLUGIN_SRC=%~dp0"
if "%PLUGIN_SRC:~-1%"=="\" set "PLUGIN_SRC=%PLUGIN_SRC:~0,-1%"
set "PLUGIN_DIR=%USERPROFILE%\.claude\plugins\tokka-mo"

echo tokka-mo installer
echo   source: %PLUGIN_SRC%

REM Check Python
where py >NUL 2>&1
if errorlevel 1 (
  where python >NUL 2>&1
  if errorlevel 1 (
    echo ERROR: Python not found on PATH. Install Python 3.10+ first.
    exit /b 1
  )
)

REM Register plugin via mklink /D (requires admin OR Developer Mode)
if exist "%PLUGIN_DIR%" rmdir /S /Q "%PLUGIN_DIR%"
mklink /D "%PLUGIN_DIR%" "%PLUGIN_SRC%" >NUL 2>&1
if errorlevel 1 (
  echo NOTE: mklink failed (need admin or Developer Mode). Falling back to copy.
  xcopy /E /I /Y "%PLUGIN_SRC%" "%PLUGIN_DIR%" >NUL
)
echo   linked plugin to %PLUGIN_DIR%

REM Config + cache dirs
if not exist "%APPDATA%\tokka-mo" mkdir "%APPDATA%\tokka-mo"
if not exist "%LOCALAPPDATA%\tokka-mo" mkdir "%LOCALAPPDATA%\tokka-mo"
echo   created %APPDATA%\tokka-mo and %LOCALAPPDATA%\tokka-mo

REM Add bin/tokka-mo.bat to user PATH if not present
echo.
echo NOTE: Add %PLUGIN_SRC%\bin to your user PATH for `tokka-mo` to work in a shell.
echo Then open Claude Code and run /login.
```

- [ ] **Step 3: Write the full `README.md`**

````markdown
# tokka-mo — Tokka Labs MO Claude Code Plugin

Submit Tokka Labs Middle Office **CASHFLOW** trade bookings as drafts directly from Claude Code. Approvals continue to happen in the web app at `mo-tools.tokkalabs.com/pending`.

**Status:** v0.1 — CASHFLOW only. SPOT support and rollout polish in Phase 2 / Phase 3.

## Prerequisites

- macOS, Linux, or Windows 10+
- Python 3.10 or newer (`python3 --version`)
- Git with Bitbucket SSH access to `tokkalabs/middle-office-tools` (the plugin lives in `plugin/` inside this repo)
- Claude Code installed (`claude --version`)
- A Middle Office account in good standing on the target environment (UAT or PROD)

## Install (macOS / Linux)

The plugin ships inside the `middle-office-tools` repo, under `plugin/`. Clone the repo (or `git pull` if you already have it), then run the installer from the plugin directory:

```bash
# First time:
git clone ssh://git@bitbucket.org/tokkalabs/middle-office-tools.git ~/Projects/middle-office-tools
cd ~/Projects/middle-office-tools/plugin
./install.sh

# Updates later:
cd ~/Projects/middle-office-tools && git pull
# (no re-install needed unless install.sh itself changed)
```

The installer symlinks `plugin/` into `~/.claude/plugins/tokka-mo` and the CLI into `~/.local/bin/tokka-mo`.

## Install (Windows)

```cmd
git clone ssh://git@bitbucket.org/tokkalabs/middle-office-tools.git %USERPROFILE%\Projects\middle-office-tools
cd %USERPROFILE%\Projects\middle-office-tools\plugin
install.bat
```

## First-time login

```bash
tokka-mo login --api-url https://mo-tools.tokkalabs.com
# Username: <you>
# Password: ******
# Logged in as <you>. Token tkmo_a1b2… expires 2026-08-24T...
```

For UAT/staging:
```bash
tokka-mo login --api-url https://mo-tools-uat.tokkalabs.com
```

Sanity check:
```bash
tokka-mo whoami
tokka-mo refdata refresh
```

## Common workflows

### Single booking (in Claude Code)

```
/book 500 USDC OPEX out of CDA to TOKKA TREASURY
```

Claude will ask for missing fields, preview, require `y` confirmation, then submit. The draft shows up at `mo-tools.tokkalabs.com/pending` for your review and approval.

### Batch booking (in Claude Code)

Paste a multi-line list into Claude Code after `/book`:
```
/book
funding in to 8006 from Galaxy: 100k USDC
funding in to 8006 from Galaxy: 200k USDC
OPEX outgoing from 8006: 10k USDC to OFFICE VENDOR
```

### Inspecting drafts

```
/drafts
```
…or from a terminal:
```bash
tokka-mo drafts list
tokka-mo drafts list --status PENDING_REVIEW
tokka-mo drafts list --batch <batch-uuid>
```

### Approving a draft

The CLI doesn't approve. Open `https://mo-tools.tokkalabs.com/pending` (or `/pending` on whichever env you're using), review, and click Approve.

## Updating the plugin

```bash
cd ~/Projects/middle-office-tools && git pull
```

(The plugin lives in `plugin/` inside this repo and is symlinked into `~/.claude/plugins/tokka-mo`, so a single `git pull` updates both the server-side scripts and the plugin.)

No reinstall needed unless `plugin/install.sh` itself changed — the plugin CHANGELOG will say.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `tokka-mo: command not found` | `~/.local/bin` (or repo `bin/`) not on PATH | `export PATH="$HOME/.local/bin:$PATH"` in your shell rc; reopen the terminal |
| `not logged in; run: tokka-mo login` | No credentials file or it was cleared | Run `/login` or `tokka-mo login --api-url <url>` |
| `Token rejected — run: tokka-mo login` | Token expired or revoked | Re-login |
| `validation failed: portfolio_id 8006 not in refdata` | Stale refdata cache | `tokka-mo refdata refresh` |
| `cannot reach https://mo-tools…` | VPN / DNS / server down | Confirm VPN; `curl <url>/api/health` |
| `Token mint failed: HTTP 401` after entering credentials | Wrong password or account suspended | Confirm in the web app at the same URL |
| `git clone` hangs | SSH key not loaded into Bitbucket profile | Check `ssh-add -L`; add to Bitbucket SSH keys |
| Windows `mklink` fails | Need admin OR Developer Mode | Right-click cmd → Run as Admin, OR enable Developer Mode in Settings → Privacy → For Developers |

## Filing issues

Bugs and feedback: `#mo-trade-booking` Slack channel, tagged `[tokka-mo-plugin]`.

## License

Proprietary — Tokka Labs Pte Ltd. See `LICENSE`.
````

- [ ] **Step 4: Commit**

```bash
git add install.sh install.bat README.md
git commit -m "feat(plugin): installer + full README"
```

---

## Task 15: End-to-end smoke script

**Goal:** `smoke.sh` exercises the full happy path against UAT in one go: login, refdata, single book, batch book, drafts list, logout. Prints PASS/FAIL.

**Files:**
- Create: `$REPO/smoke.sh`

**Acceptance Criteria:**
- [ ] `./smoke.sh --base-url https://mo-tools-uat.tokkalabs.com --username <u> --password <p>` exits 0 and prints `PASS` if all steps succeed
- [ ] Each step prints `✓ <step>` on success or `✗ <step>: <reason>` on failure
- [ ] On failure, exits with the step's exit code
- [ ] Cleans up: the test drafts are surfaced in the output for the user to reject in the UI (we don't auto-reject — that requires the approval workflow)

**Verify:** Run the smoke against UAT.

**Steps:**

- [ ] **Step 1: Write `smoke.sh`**

```bash
#!/usr/bin/env bash
# tokka-mo end-to-end smoke against an MO environment.
# Usage:
#   ./smoke.sh --base-url https://mo-tools-uat.tokkalabs.com --username <u> --password <p>

set -e

BASE_URL=""
USERNAME=""
PASSWORD=""

while [ $# -gt 0 ]; do
  case "$1" in
    --base-url) BASE_URL="$2"; shift 2 ;;
    --username) USERNAME="$2"; shift 2 ;;
    --password) PASSWORD="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$BASE_URL" ] || [ -z "$USERNAME" ] || [ -z "$PASSWORD" ]; then
  echo "usage: ./smoke.sh --base-url URL --username USER --password PASS" >&2
  exit 2
fi

TOKKA_MO="$(cd "$(dirname "$0")" && pwd)/bin/tokka-mo"
[ -x "$TOKKA_MO" ] || chmod +x "$TOKKA_MO"

fail() { echo "✗ $1: $2" >&2; exit 1; }
ok()   { echo "✓ $1"; }

# 1. Login (two lines on stdin: username, password)
printf '%s\n%s\n' "$USERNAME" "$PASSWORD" \
  | $TOKKA_MO --api-url "$BASE_URL" login --non-interactive >/dev/null \
  || fail "login" "auth failed (check creds + URL)"
ok "login"

# 2. whoami
out=$($TOKKA_MO whoami) || fail "whoami" "$out"
ok "whoami: $out"

# 3. refdata refresh
out=$($TOKKA_MO refdata refresh) || fail "refdata refresh" "$out"
ok "refdata refresh: $out"

# 4. single book
TS=$(date -u +"%Y-%m-%dT%H:%M:%S+00:00")
cat <<EOF | $TOKKA_MO book > /tmp/single_out.txt || fail "single book" "$(cat /tmp/single_out.txt)"
{
  "cashflow_type": "OPEX",
  "direction": "OUTGOING",
  "entity": "TOKKA LABS PTE LTD",
  "portfolio_id": 8006,
  "portfolio_name": "CDA",
  "counterparty": "TOKKA TREASURY",
  "account": "TOKKA TREASURY WALLET",
  "account_type": "WALLET",
  "asset": "USDC",
  "amount": "1",
  "trade_date": "${TS}",
  "value_date": "${TS}",
  "user_id": "${USERNAME}",
  "status": "PENDING"
}
EOF
SINGLE_ID=$(grep -oE 'Draft #[0-9]+' /tmp/single_out.txt | head -1 | tr -dc 0-9)
[ -n "$SINGLE_ID" ] || fail "single book" "no draft id in output"
ok "single book → draft #${SINGLE_ID}"

# 5. batch book (2 rows)
cat <<EOF | $TOKKA_MO book-batch > /tmp/batch_out.txt || fail "batch book" "$(cat /tmp/batch_out.txt)"
{"trades":[
 {"payload":{"cashflow_type":"OPEX","direction":"OUTGOING","entity":"TOKKA LABS PTE LTD","portfolio_id":8006,"portfolio_name":"CDA","counterparty":"TOKKA TREASURY","account":"TOKKA TREASURY WALLET","account_type":"WALLET","asset":"USDC","amount":"2","trade_date":"${TS}","value_date":"${TS}","user_id":"${USERNAME}","status":"PENDING"}},
 {"payload":{"cashflow_type":"OPEX","direction":"OUTGOING","entity":"TOKKA LABS PTE LTD","portfolio_id":8006,"portfolio_name":"CDA","counterparty":"TOKKA TREASURY","account":"TOKKA TREASURY WALLET","account_type":"WALLET","asset":"USDC","amount":"3","trade_date":"${TS}","value_date":"${TS}","user_id":"${USERNAME}","status":"PENDING"}}
]}
EOF
BATCH_OUT=$(cat /tmp/batch_out.txt)
[[ "$BATCH_OUT" == *"2 drafts created"* ]] || fail "batch book" "$BATCH_OUT"
ok "batch book: $BATCH_OUT"

# 6. drafts list
out=$($TOKKA_MO drafts list --status PENDING_REVIEW) || fail "drafts list" "$out"
[ -n "$out" ] || fail "drafts list" "empty output"
ok "drafts list (PENDING_REVIEW shown)"

# 7. logout
$TOKKA_MO logout >/dev/null || fail "logout" "(see stderr)"
ok "logout"

echo
echo "PASS"
echo
echo "Test drafts on ${BASE_URL}:"
echo "  - single: #${SINGLE_ID}"
echo "  - batch:  $(echo "$BATCH_OUT" | grep -oE '#[0-9]+' | tr '\n' ' ')"
echo "Reject them in the /pending UI to keep UAT clean."
```

```bash
chmod +x smoke.sh
```

- [ ] **Step 2: Run the smoke against UAT**

```bash
./smoke.sh --base-url https://mo-tools-uat.tokkalabs.com --username <you> --password '<pw>'
```
Expected: ends with `PASS` and lists the test draft IDs.

- [ ] **Step 3: Reject the test drafts in the UAT UI** so the inbox doesn't accumulate noise.

- [ ] **Step 4: Commit**

```bash
git add smoke.sh
git commit -m "test: end-to-end smoke against UAT"
```

---

## Task 16: PR, merge, release, and rollout (user-driven)

**Goal:** Hand off to the dogfooder. Since the plugin lives inside `middle-office-tools`, there's no separate repo to push — the plugin ships alongside the next MO release.

**Files:**
- None modified by the engineer. This is operational.

**Acceptance Criteria:**
- [ ] PR `feature/phase-1b-plugin` → `main` opened on Bitbucket, reviewed, merged
- [ ] Plugin tagged: `git tag plugin-v0.1.0 && git push origin plugin-v0.1.0` (a separate tag namespace from the server's release tags, so plugin versioning stays independent)
- [ ] Dogfooder pulls latest `main`, runs `cd plugin && ./install.sh` on a clean laptop, reaches "logged in" within 5 minutes
- [ ] Dogfooder books 1 single + 1 batch (3-row) against PROD, sees both in `/pending`, approves all, all rows land in `trades_cashflow` with `tradeSource='CLAUDE_CODE'` (or whatever the existing approve path stamps — confirm by reading `scripts/cashflow_insert.py`)

**Steps (user-driven, NOT automated):**

- [ ] **Step 1: Pre-flight against PROD**

Confirm Phase 1a is deployed to PROD (the plugin needs the `/api/bookings/draft(s)` endpoints there):
```bash
curl https://mo-tools.tokkalabs.com/api/health
# expect: 200 OK
```

Confirm the schema was migrated:
```bash
# from middle-office-tools, against PROD env vars
python scripts/apply_schema_drafts.py
# expect: ok: bookings_draft table ready
```

If either fails: pause Plan 1b rollout and finish Phase 1a Task 16 first.

- [ ] **Step 2: Push the feature branch and open the PR**

```bash
cd ~/Projects/middle-office-tools
git push -u origin feature/phase-1b-plugin
# Open PR on Bitbucket: feature/phase-1b-plugin → main
# Reviewer focus: plugin/ is brand-new, no server-side changes touched.
```

- [ ] **Step 3: Merge to main and tag**

After PR approval and merge:
```bash
git checkout main && git pull
git tag plugin-v0.1.0
git push origin plugin-v0.1.0
```

- [ ] **Step 4: Dogfooder install + first booking against PROD**

On the dogfooder's laptop:
```bash
# If they don't have the repo yet:
git clone ssh://git@bitbucket.org/tokkalabs/middle-office-tools.git ~/Projects/middle-office-tools
# OR if they already have it:
cd ~/Projects/middle-office-tools && git checkout main && git pull

cd ~/Projects/middle-office-tools/plugin
./install.sh
tokka-mo login --api-url https://mo-tools.tokkalabs.com
tokka-mo whoami
```

Then in Claude Code: `/book 1 USDC OPEX out of CDA to TOKKA TREASURY` — through the full preview/y/submit/review/approve loop.

- [ ] **Step 5: Sign-off**

If the dogfooder reports success, this completes Plan 1b. Open Plan 2a (SPOT support) when ready.

- [ ] **Step 6: Update memory**

Add a `project_phase_1b_plugin.md` entry to user auto-memory: status (shipped / in dogfood / not deployed), dogfooder list, link to the `plugin-v0.1.0` tag.

---

## Definition of Done (entire plan)

- [ ] All 15 implementation tasks complete (Task 16 = user-driven rollout)
- [ ] `cd plugin && python -m pytest tests/test_tokka_mo.py -v` → all PASS
- [ ] `cd plugin && ./smoke.sh --base-url <UAT> --username <u> --password <p>` → PASS
- [ ] Dogfooder books one single + one batch against PROD via Claude Code, both visible in `/pending`, both approve cleanly, both land in `trades_cashflow`
- [ ] README install one-liner works on a clean macOS laptop and a clean Windows 10 box
- [ ] Tag `plugin-v0.1.0` pushed to Bitbucket; `feature/phase-1b-plugin` merged to `main`

---

## Out of scope (deferred to Phase 2 / Phase 3)

- **SPOT trade type support** — Phase 2. The CLI structure is ready (the `category` field already passes through); the skill needs SPOT-specific parsing + reference; `validate_spot_payload` needs writing.
- **`tokka-mo drafts approve` / `reject`** — the CLI can already read drafts; approve/reject is currently UI-only. Adding it requires deciding the UX (preview + y for approve from CLI). Phase 2.
- **Auto-update** — v0.1 uses `git pull`. Phase 3 may package as a self-contained binary.
- **Cross-platform installer polish** — the Windows `mklink` fallback is rough. Phase 3.
- **Rejection reasons surfaced back in CLI** — `tokka-mo drafts list --status REJECTED` will show them, but no proactive notification. Phase 3.
- **Multi-user batches** — not supported by the server; out of scope.

---

## Risks captured in design doc Section 9

The plugin-relevant risks (1, 2, 4, 8, 9) all have mitigations that this plan implements:

| Risk | Where addressed in this plan |
|---|---|
| #1 LLM hallucinates wrong value | Task 8 (local refdata validation) + Task 12 (skill requires `y`) + server checks at approve time |
| #2 Refdata cache goes stale | Task 6 (24h TTL) + Task 7 (manual refresh) + server-side check unchanged |
| #4 Server schema drift | Task 9/10 surface server error messages verbatim |
| #8 Install friction | Task 14 (installers + README troubleshooting table) |
| #9 Plugin/server version skew | Out of v0.1 — defer to a `tokka-mo whoami --server-version` follow-up in Phase 3 |

---

## Notes for the engineer

- **Everything lives inside `middle-office-tools/plugin/`.** When the plan says `cd $PLUGIN_DIR` it means `cd ~/Projects/middle-office-tools/plugin`. All relative paths in code blocks (`bin/tokka-mo`, `tests/test_tokka_mo.py`) resolve from that directory.
- **Python stdlib only.** No `requests`, no `pyyaml`, no `pydantic`. Anything you need, write inline.
- **Single-file CLI.** Resist the urge to split into a package — keep `bin/tokka-mo` as one file. It's small enough.
- **Tests stay in `plugin/tests/` and never import `urllib.request` against the real internet.** Use `monkeypatch` to fake the wire if you need HTTP-touching tests; everything else stays pure-logic.
- **Match Phase 1a's commit message style.** Look at recent commits on `feature/phase-1a-drafts`. Subject ≤ 72 chars; co-author trailer if you're agentic. Scope commits with `(plugin)` to make them easy to filter: `feat(plugin): ...`.
- **Don't touch server-side code in this branch.** Plan 1b is a pure additive layer in `plugin/`. If you find a server-side bug, file it separately or fix on a different branch.

---

**Plan complete.** Ready for `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to execute.
