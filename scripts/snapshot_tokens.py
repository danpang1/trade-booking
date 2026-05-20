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
import os
from datetime import datetime, timezone
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
JS_OUT = ROOT / "src" / "data" / "tokens.js"
JSON_OUT = ROOT / "public" / "tokens.json"


def _load_credentials() -> dict[str, str]:
    """Env vars (TOKEN_PRICE_*) take precedence; .env file parsed as fallback."""
    env_creds = {
        k: os.environ[f"TOKEN_PRICE_{k.upper()}"]
        for k in ("host", "username", "password")
        if f"TOKEN_PRICE_{k.upper()}" in os.environ
    }
    if all(k in env_creds for k in ("host", "username", "password")):
        return env_creds

    if not ENV_PATH.exists():
        raise FileNotFoundError(
            f".env not found at {ENV_PATH} and TOKEN_PRICE_* env vars are incomplete"
        )
    creds: dict[str, str] = {}
    in_block = False
    for line in ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if "MYSQL TOKEN PRICE DB" in s.upper():
            in_block = True
            continue
        if not in_block:
            continue
        if not s or s.startswith("#"):
            if s.startswith("#") and "MYSQL" not in s.upper():
                break
            continue
        if ":" in s:
            k, _, v = s.partition(":")
            creds[k.strip().lower()] = v.strip()
    missing = [k for k in ("username", "password", "host") if k not in creds]
    if missing:
        raise RuntimeError(f"MySQL creds missing keys: {missing}")
    return creds


def _connect(database: str = "reference_data"):
    c = _load_credentials()
    return pymysql.connect(
        host=c["host"],
        user=c["username"],
        password=c["password"],
        database=database,
        connect_timeout=15,
        read_timeout=60,
    )

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
