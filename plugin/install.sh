#!/usr/bin/env bash
# tokka-mo Claude Code plugin installer (macOS / Linux).
#
# Usage:
#   ./install.sh                  # install from this local clone
#   ./install.sh --remote         # install from the Bitbucket remote (sparse)
#
# Prefer running this from inside a clone of middle-office-tools so the
# marketplace points at your local copy (instant updates via `git pull`).
# Use --remote if you don't want a clone — Claude Code will fetch only
# the plugin/ + .claude-plugin/ folders (~50 KB).

set -euo pipefail

REMOTE=false
if [ "${1:-}" = "--remote" ]; then
  REMOTE=true
fi

PLUGIN_SRC="$(cd "$(dirname "$0")/.." && pwd)"   # ...middle-office-tools (repo root)

echo "tokka-mo installer"

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
echo "  ✓ Python ${PY_MAJOR}.${PY_MINOR} OK"

# Verify Claude Code is on PATH
if ! command -v claude >/dev/null 2>&1; then
  echo "ERROR: 'claude' command not found. Install Claude Code from claude.com/code first." >&2
  exit 1
fi
echo "  ✓ Claude Code OK"

# Register the marketplace
if $REMOTE; then
  MARKETPLACE_SRC="ssh://git@bitbucket.org/tokkalabs/middle-office-tools.git"
  echo "  → registering marketplace from Bitbucket (sparse: plugin/ + .claude-plugin/)"
  claude plugin marketplace add "$MARKETPLACE_SRC" --sparse plugin .claude-plugin || true
else
  MARKETPLACE_SRC="$PLUGIN_SRC"
  echo "  → registering marketplace from ${MARKETPLACE_SRC}"
  claude plugin marketplace add "$MARKETPLACE_SRC" || true
fi

# Install the plugin
echo "  → installing tokka-mo@tokka-mo-marketplace"
claude plugin install tokka-mo@tokka-mo-marketplace

# Ensure local config + cache dirs exist
mkdir -p "${HOME}/.config/tokka-mo" "${HOME}/.cache/tokka-mo"
chmod 700 "${HOME}/.config/tokka-mo"
echo "  ✓ created ${HOME}/.config/tokka-mo (chmod 700) and ${HOME}/.cache/tokka-mo"

echo
echo "Done. Restart any running Claude Code session ('/exit' then 'claude')"
echo "so it picks up the new plugin, then try:"
echo "  /tokka-mo:login           # first-time auth"
echo "  /tokka-mo:book ...        # book a CASHFLOW draft"
echo "  /tokka-mo:drafts          # list your drafts"
