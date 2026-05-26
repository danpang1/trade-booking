# tokka-mo — Tokka Labs MO Claude Code Plugin

Submit Tokka Labs Middle Office **CASHFLOW** trade bookings as drafts directly from Claude Code. Approvals continue to happen in the web app at `sg-tms.internal.tokkalabs.com/pending`.

**Status:** v0.1 — CASHFLOW only. SPOT support and rollout polish in Phase 2 / Phase 3.

> **Not sure how to install?** Paste this whole README into Claude Code (or claude.ai) and ask: **"Walk me through installing this on my <macOS / Windows / Linux> laptop."** Claude will identify which prerequisites you're missing, pick the right install path for your OS, and explain each step. Get stuck? Send Claude the exact error message — most failures are in the Troubleshooting table at the bottom.

## Prerequisites

If any of these aren't already true, paste this section into Claude and ask "help me set up <item>." For items requiring access from Tokka (Bitbucket repo, MO account), ping `#mo-trade-booking` first.

- **macOS, Linux, or Windows 10+** — any modern laptop
- **Python 3.10 or newer** — check with `python3 --version`. To install: macOS → `brew install python@3.11`; Windows → download from python.org; Linux → use your distro's package manager
- **Git with Bitbucket SSH access to `tokkalabs/middle-office-tools`** — you need (a) your Bitbucket account added to the repo by a Tokka admin AND (b) an SSH key on your laptop registered in your Bitbucket profile (Bitbucket → Personal settings → SSH keys). Test with `ssh -T git@bitbucket.org` — should say "logged in as <you>".
- **Claude Code installed** — `claude --version` should work. If not, install from `claude.com/code`.
- **A Middle Office account in good standing** on the target environment (UAT or PROD).
- **Tokka VPN connection** — both UAT (`test-jp-tms.internal.tokkalabs.com`) and PROD (`sg-tms.internal.tokkalabs.com`) are on the internal network. The plugin won't reach the server if you're off-VPN; you'll see `cannot reach <url>: nodename nor servname provided`.

## Install (recommended — two commands)

The plugin installs from `middle-office-tools` itself, which doubles as a Claude Code marketplace. No `git clone` required — Claude Code does the fetch.

```bash
claude plugin marketplace add ssh://git@bitbucket.org/tokkalabs/middle-office-tools.git --sparse plugin .claude-plugin
claude plugin install tokka-mo@tokka-mo-marketplace
```

That's it. The `--sparse` flag tells Claude Code to only fetch the `plugin/` and `.claude-plugin/` directories (about 50 KB) instead of the whole `middle-office-tools` repo.

Verify it's installed:

```bash
claude plugin list
# Look for: tokka-mo@tokka-mo-marketplace ✔ enabled
```

**Restart any running Claude Code session** (`/exit` then `claude`) so it picks up the new plugin.

## Install (alternative — local path, for engineers with the repo cloned)

If you already have `middle-office-tools` cloned locally:

```bash
cd ~/Projects/middle-office-tools   # or wherever your clone lives
claude plugin marketplace add .
claude plugin install tokka-mo@tokka-mo-marketplace
```

## First-time login

The CLI talks to the MO server using a Bearer token. First time, run:

```bash
# In Claude Code:
/tokka-mo:login
```

…and follow the prompt. Or from a terminal directly (recommended — keeps password out of Claude Code chat history):

```bash
# Find the installed CLI (the version number is in the path):
TOKKA_MO=$(ls -d ~/.claude/plugins/cache/tokka-mo-marketplace/tokka-mo/*/bin/tokka-mo | tail -1)

$TOKKA_MO login --api-url https://sg-tms.internal.tokkalabs.com
```

For convenience, alias it once:
```bash
echo 'alias tokka-mo="$(ls -d $HOME/.claude/plugins/cache/tokka-mo-marketplace/tokka-mo/*/bin/tokka-mo | tail -1)"' >> ~/.zshrc
source ~/.zshrc
# now you can just: tokka-mo login --api-url ...
```

For UAT/staging: use `--api-url https://test-jp-tms.internal.tokkalabs.com` instead.

Sanity check (in Claude Code):

```
/tokka-mo:login
```

It'll prompt for username and password and save a 90-day Bearer token at `~/.config/tokka-mo/credentials` (chmod 600).

## Common workflows (all in Claude Code)

### Single booking

```
/tokka-mo:book 500 USDC OPEX out of CDA to TOKKA TREASURY
```

Claude asks for missing fields, shows a preview, requires `y` to confirm, then submits. The draft shows up at `sg-tms.internal.tokkalabs.com/pending` for review and approval.

### Batch booking

Paste a multi-line list after `/tokka-mo:book`:
```
/tokka-mo:book
funding in to 8006 from Galaxy: 100k USDC
funding in to 8006 from Galaxy: 200k USDC
OPEX outgoing from 8006: 10k USDC to OFFICE VENDOR
```

### Inspecting drafts

```
/tokka-mo:drafts
```

### Approving a draft

The plugin doesn't approve. Open `https://sg-tms.internal.tokkalabs.com/pending`, review, and click Approve.

## Updating the plugin

```bash
claude plugin update tokka-mo@tokka-mo-marketplace
```

Then restart Claude Code.

## Uninstalling

```bash
claude plugin uninstall tokka-mo@tokka-mo-marketplace
claude plugin marketplace remove tokka-mo-marketplace   # optional
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `/tokka-mo:book` etc. don't appear in /help | Plugin not loaded — Claude Code wasn't restarted after install | `/exit` then `claude` again |
| `claude plugin marketplace add` fails with SSH error | Your SSH key isn't registered with Bitbucket | Test with `ssh -T git@bitbucket.org`; add your key in Bitbucket → Personal settings → SSH keys |
| Bitbucket "repo not found" | Your account doesn't have access | Ping `#mo-trade-booking` to get added to `tokkalabs/middle-office-tools` |
| `not logged in; run: tokka-mo login` | No credentials file or it was cleared | Run `/tokka-mo:login` |
| `Token rejected — run: tokka-mo login` | Token expired or revoked | Re-login |
| `validation failed: portfolio_id 8006 not in refdata` | Stale refdata cache | The skill auto-refreshes; if it persists, ping `#mo-trade-booking` |
| `cannot reach <url>: nodename nor servname...` | Tokka VPN not connected (internal DNS unreachable) | Connect to the Tokka VPN; retry. Confirm with `curl https://sg-tms.internal.tokkalabs.com/api/health` |
| Token mint failed: HTTP 401 after entering credentials | Wrong password or account suspended | Confirm in the web app at the same URL |

## Filing issues

Bugs and feedback: `#mo-trade-booking` Slack channel, tagged `[tokka-mo-plugin]`.

## License

Proprietary — Tokka Labs Pte Ltd. See repo-root `LICENSE`.
