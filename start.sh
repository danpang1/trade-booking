#!/bin/bash
# ================================================================
# Tokka MO — Manual Trade Booking (standalone module)
# Usage: ./start.sh (or: bash start.sh)
# ================================================================

# Run from this script's directory regardless of where it's launched
cd "$(dirname "$0")" || exit 1

echo
echo "=== Tokka MO — Manual Trade Booking ==="
echo

# Auto-install if node_modules is missing
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies (first run only)..."
    if ! npm install; then
        echo
        echo "ERROR: npm install failed. Make sure Node.js is installed."
        echo "Download from https://nodejs.org/"
        exit 1
    fi
    echo
fi

echo "Starting Vite dev server on http://localhost:5180"
echo "Press Ctrl+C to stop the server."
echo "---"

# Open the browser after a short delay so Vite has time to bind
(sleep 3 && {
    if command -v open >/dev/null 2>&1; then open http://localhost:5180/
    elif command -v xdg-open >/dev/null 2>&1; then xdg-open http://localhost:5180/
    fi
}) &

# Run Vite in the foreground
npm run dev
