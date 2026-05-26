# tokka-mo — Tokka Labs MO Claude Code Plugin

Submit Tokka Labs Middle Office **CASHFLOW** trade bookings as drafts directly from Claude Code. Approvals continue to happen in the web app at `mo-tools.tokkalabs.com/pending`.

**Status:** v0.1 — CASHFLOW only. SPOT support and rollout polish in Phase 2 / Phase 3.

> **Not sure how to install?** Paste this whole README into Claude Code (or claude.ai) and ask: **"Walk me through installing this on my <macOS / Windows / Linux> laptop."** Claude will identify which prerequisites you're missing, pick the right install path for your OS, and explain each step. Get stuck? Send Claude the exact error message — most failures are in the Troubleshooting table at the bottom.

## Prerequisites

If any of these aren't already true, paste this section into Claude and ask "help me set up <item>." For items requiring access from Tokka (Bitbucket repo, MO account), ping `#mo-trade-booking` first.

- **macOS, Linux, or Windows 10+** — any modern laptop
- **Python 3.10 or newer** — check with `python3 --version`. To install: macOS → `brew install python@3.11`; Windows → download from python.org; Linux → use your distro's package manager
- **Git with Bitbucket SSH access to `tokkalabs/middle-office-tools`** — you need (a) your Bitbucket account added to the repo by a Tokka admin AND (b) an SSH key on your laptop registered in your Bitbucket profile (Bitbucket → Personal settings → SSH keys). Test with `ssh -T git@bitbucket.org` — should say "logged in as <you>".
- **Claude Code installed** — `claude --version` should work. If not, install from `claude.com/code`.
- **A Middle Office account in good standing** on the target environment (UAT or PROD). You can log in to `mo-tools.tokkalabs.com` with the same username + password you'll use for `tokka-mo login`.

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

## Lightweight install (plugin only — for non-engineers)

If you don't need the rest of the `middle-office-tools` repo (e.g. you're a non-engineering team member who just wants the plugin), use Git's sparse-checkout to pull **only** the `plugin/` folder (~50 KB instead of the full repo):

**macOS / Linux:**
```bash
mkdir -p ~/.claude/plugins/tokka-mo-src
cd ~/.claude/plugins/tokka-mo-src
git clone --depth 1 --filter=blob:none --sparse \
  ssh://git@bitbucket.org/tokkalabs/middle-office-tools.git .
git sparse-checkout set plugin
cd plugin && ./install.sh
```

**Windows:**
```cmd
mkdir "%USERPROFILE%\.claude\plugins\tokka-mo-src"
cd /d "%USERPROFILE%\.claude\plugins\tokka-mo-src"
git clone --depth 1 --filter=blob:none --sparse ^
  ssh://git@bitbucket.org/tokkalabs/middle-office-tools.git .
git sparse-checkout set plugin
cd plugin
install.bat
```

Updates work the same as the full install:
```bash
cd ~/.claude/plugins/tokka-mo-src && git pull
```

## First-time login

```bash
tokka-mo login --api-url https://mo-tools.tokkalabs.com
# Username: <you>
# Password: ******
# Logged in as <you>. Token tkmo_a1b2... expires 2026-08-24T...
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
| `cannot reach https://mo-tools...` | VPN / DNS / server down | Confirm VPN; `curl <url>/api/health` |
| `Token mint failed: HTTP 401` after entering credentials | Wrong password or account suspended | Confirm in the web app at the same URL |
| `git clone` hangs | SSH key not loaded into Bitbucket profile | Check `ssh-add -L`; add to Bitbucket SSH keys |
| Windows `mklink` fails | Need admin OR Developer Mode | Right-click cmd → Run as Admin, OR enable Developer Mode in Settings → Privacy → For Developers |

## Filing issues

Bugs and feedback: `#mo-trade-booking` Slack channel, tagged `[tokka-mo-plugin]`.

## License

Proprietary — Tokka Labs Pte Ltd. See repo-root `LICENSE`.
