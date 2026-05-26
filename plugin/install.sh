#!/usr/bin/env bash
# tokka-mo Claude Code plugin installer (macOS / Linux).
# Run from inside the plugin directory:
#   cd <middle-office-tools>/plugin && ./install.sh
#
# Idempotent. Safe to re-run after `git pull` to update.

set -euo pipefail

PLUGIN_SRC="$(cd "$(dirname "$0")" && pwd)"      # ...middle-office-tools/plugin
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
echo "  linked plugin to ${PLUGIN_DIR}"

# Make CLI executable
chmod +x "${PLUGIN_SRC}/bin/tokka-mo"

# Symlink CLI into ~/.local/bin for PATH access
mkdir -p "$(dirname "$BIN_LINK")"
ln -sf "${PLUGIN_SRC}/bin/tokka-mo" "$BIN_LINK"
echo "  linked CLI to ${BIN_LINK}"

# Ensure config + cache dirs exist
mkdir -p "${HOME}/.config/tokka-mo" "${HOME}/.cache/tokka-mo"
chmod 700 "${HOME}/.config/tokka-mo"
echo "  created ${HOME}/.config/tokka-mo (chmod 700) and ${HOME}/.cache/tokka-mo"

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
