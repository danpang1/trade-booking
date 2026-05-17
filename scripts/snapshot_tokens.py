"""Snapshot reference_data.instrument_token_grouped.

Writes two files:
  - src/data/tokens.js    : bundled seed (compiled into the JS bundle so the
                            picker has data on cold start / when the API server
                            is not running).
  - public/tokens.json    : runtime data fetched by the form on mount. Vite
                            serves files from public/ at the site root, so
                            the browser hits /tokens.json. Refreshed hourly
                            by server.js.

Filters: deletedAt IS NULL AND status='ACTIVE'.
Dedupe by commonIdentifier (ticker), keeping the first occurrence
ordered by id ascending (earliest canonical row).
Each entry: { symbol, name }.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_PNL_DIR = Path(__file__).resolve().parents[2] / "scripts" / "pnl"
sys.path.insert(0, str(_PNL_DIR))
from mysql_rates import _connect

ROOT = Path(__file__).resolve().parents[1]
JS_OUT = ROOT / "src" / "data" / "tokens.js"
JSON_OUT = ROOT / "public" / "tokens.json"

conn = _connect("reference_data")
cur = conn.cursor()
cur.execute("""
    SELECT id, commonIdentifier, name
    FROM instrument_token_grouped
    WHERE deletedAt IS NULL AND status='ACTIVE'
      AND commonIdentifier IS NOT NULL
      AND commonIdentifier <> ''
    ORDER BY commonIdentifier ASC, id ASC
""")
rows = cur.fetchall()
conn.close()

seen = set()
tokens = []
for _id, sym, name in rows:
    s = sym.strip()
    if s in seen:
        continue
    seen.add(s)
    tokens.append({"symbol": s, "name": (name or "").strip()})

print(f"unique tokens: {len(tokens)}")

# ── public/tokens.json (runtime fetch) ───────────────────────
JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
payload = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "source": "reference_data.instrument_token_grouped",
    "filter": "deletedAt IS NULL AND status='ACTIVE'",
    "tokens": tokens,
}
JSON_OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
print(f"wrote {JSON_OUT}")

# ── src/data/tokens.js (bundled seed) ────────────────────────
lines = [
    "// Auto-generated snapshot from MySQL reference_data.instrument_token_grouped.",
    "// Bundled seed for cold-start / offline. Live data fetched at runtime",
    "// from /tokens.json (refreshed hourly by server.js).",
    "// Regenerate via: python scripts/snapshot_tokens.py",
    "",
    "export const TOKENS = [",
]
for t in tokens:
    sym = t["symbol"].replace('\\', '\\\\').replace('"', '\\"')
    name = t["name"].replace('\\', '\\\\').replace('"', '\\"')
    lines.append(f'  {{ symbol: "{sym}", name: "{name}" }},')
lines.append("];")
lines.append("")
lines.append("export const ASSET_SYMBOLS = TOKENS.map((t) => t.symbol);")
lines.append("")

JS_OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"wrote {JS_OUT}")
