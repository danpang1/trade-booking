"""Postgres (tq_oms_data balance DB) creds from the local .env.

Reads the `#POSTGRES BALANCE DB` block (Host/Port/Username/Password/Database).
Standalone replacement for nxgenmo's daily_pipeline PG_* constants.
"""
from __future__ import annotations

import re
from pathlib import Path

ENV = Path(__file__).resolve().parent / ".env"

_env: dict[str, str] = {}
for _ln in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
    _s = _ln.strip()
    if not _s or _s.startswith("#"):
        continue
    _m = re.match(r"^([A-Za-z0-9_@.]+)\s*[:=]\s*(.+?)\s*$", _s)
    if _m:
        _env[_m.group(1)] = _m.group(2).strip().strip('"').strip("'")

PG_HOST = _env.get("Host", "")
PG_PORT = int(_env.get("Port", "5432"))
PG_USER = _env.get("Username", "")
PG_PASS = _env.get("Password", "")
PG_DB = _env.get("Database", "")
