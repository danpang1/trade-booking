"""Shared helper for cashflow_insert/amend/recent/get scripts.

Pure logic (validation, (de)serialization) lives here for unit testing.
DB-touching scripts call into here for creds + connection.
"""
from __future__ import annotations
from pathlib import Path
import psycopg2

REPO = Path(__file__).resolve().parents[2]
ENV = REPO / ".env"


def load_creds() -> dict[str, str]:
    """Parse the #MO DB UAT block from <repo>/.env.

    Same convention as apply_schema_cashflow.py — block starts at the
    `# MO DB UAT` marker and ends at the next `#` comment that isn't the
    marker or at EOF.
    """
    creds: dict[str, str] = {}
    in_block = False
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if "MO DB UAT" in s.upper():
            in_block = True
            continue
        if not in_block:
            continue
        if not s or s.startswith("#"):
            if s.startswith("#") and "MO DB UAT" not in s.upper():
                break
            continue
        if ":" in s:
            k, _, v = s.partition(":")
            creds[k.strip().lower()] = v.strip()
    return creds


def connect():
    """Open a psycopg2 connection. Caller manages txns (autocommit=False)."""
    c = load_creds()
    return psycopg2.connect(
        host=c["host"],
        port=int(c.get("port", "5432")),
        dbname=c["database"],
        user=c["username"],
        password=c["password"],
        connect_timeout=15,
    )
