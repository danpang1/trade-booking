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
    """Read t2x-ro-mysql creds. Env vars (T2X_RO_MYSQL_*) take precedence;
    .env file parsed as fallback. Uses the lookback-window parser shared
    with sync_counterparties/portfolios/users (the `# t2x-ro-mysql`
    marker)."""
    env_creds = {
        k: os.environ[f"T2X_RO_MYSQL_{k.upper()}"]
        for k in ("host", "username", "password")
        if f"T2X_RO_MYSQL_{k.upper()}" in os.environ
    }
    if all(k in env_creds for k in ("host", "username", "password")):
        return env_creds

    if not ENV_PATH.exists():
        raise FileNotFoundError(
            f".env not found at {ENV_PATH} and T2X_RO_MYSQL_* env vars are incomplete"
        )

    lines = ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    creds: dict[str, str] = {}
    for i, ln in enumerate(lines):
        if "t2x-ro-mysql" in ln.lower():
            for j in range(max(0, i - 5), min(len(lines), i + 3)):
                s = lines[j].strip()
                if not s or s.startswith("#"):
                    continue
                if ":" in s:
                    k, _, v = s.partition(":")
                    creds[k.strip().lower()] = v.strip()
            break
    missing = [k for k in ("username", "password", "host") if k not in creds]
    if missing:
        raise RuntimeError(f"t2x-ro-mysql creds missing keys: {missing}")
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

# Union with `instrument_fiat` so fiat ccys (USD, EUR, etc.) book as
# `asset` on cashflow trades — same validator pathway, same picker.
cur.execute("""
    SELECT id, name
    FROM instrument_fiat
    WHERE deletedAt IS NULL AND (status IS NULL OR status='ACTIVE')
      AND name IS NOT NULL AND name <> ''
    ORDER BY name ASC, id ASC
""")
fiat_rows = cur.fetchall()
conn.close()

seen = set()
tokens = []
for _id, sym, name in rows:
    s = sym.strip()
    if s in seen:
        continue
    seen.add(s)
    tokens.append({"symbol": s, "name": (name or "").strip()})
for _id, name in fiat_rows:
    s = (name or "").strip()
    if not s or s in seen:
        continue
    seen.add(s)
    tokens.append({"symbol": s, "name": s, "kind": "FIAT"})

print(f"unique tokens: {len(tokens)} (fiat: {len(fiat_rows)})")

# ── public/tokens.json (runtime fetch) ───────────────────────
JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
payload = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "source": "reference_data.instrument_token_grouped + instrument_fiat",
    "filter": "deletedAt IS NULL AND status='ACTIVE'",
    "tokens": tokens,
}
JSON_OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
print(f"wrote {JSON_OUT}")

# ── src/data/tokens.js (bundled seed) ────────────────────────
# Only meaningful at dev/build time: Vite reads this into the bundle so
# the picker has data on cold start. The production image doesn't ship
# src/ (only dist/ + public/ + scripts/ + server.js), so skip cleanly
# when the parent directory is absent — runtime fetches /tokens.json.
if JS_OUT.parent.is_dir():
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
else:
    print(f"skip {JS_OUT} (parent dir absent — production runtime)")
