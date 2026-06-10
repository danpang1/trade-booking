"""Shared Middle Office Postgres connector for the venue-snapshot crons.

Credential resolution (matches the repo convention used by apply_schema_*.py):
  1. Env vars MO_DB_* take precedence — injected in-cluster from the k8s Secret
     `trade-booking-mo-db` (see helm_values/base.yaml env_secrets).
  2. Fallback: the `# MO DB UAT` block in the repo-root .env (local dev only).
"""
from __future__ import annotations

import os
from pathlib import Path

import psycopg2

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV = REPO_ROOT / ".env"

_KEYS = ("host", "port", "database", "username", "password")
_REQUIRED = ("host", "database", "username", "password")


def _env_block(marker: str) -> dict[str, str]:
    """Read KEY:VALUE lines under the `# {marker}` comment in .env."""
    if not ENV.exists():
        return {}
    creds: dict[str, str] = {}
    in_block = False
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("#"):
            in_block = marker.upper() in s.upper()
            continue
        if not in_block or not s or ":" not in s:
            continue
        k, _, v = s.partition(":")
        key = k.strip().lower()
        if key.startswith("mo_db_"):
            key = key[len("mo_db_"):]
        creds[key] = v.strip()
    return creds


def creds() -> dict[str, str]:
    """MO_DB_* env vars first; otherwise the `# MO DB UAT` .env block."""
    env_creds = {
        k: os.environ[f"MO_DB_{k.upper()}"]
        for k in _KEYS
        if f"MO_DB_{k.upper()}" in os.environ
    }
    if all(k in env_creds for k in _REQUIRED):
        return env_creds

    file_creds = _env_block("MO DB UAT")
    if all(k in file_creds for k in _REQUIRED):
        return file_creds

    raise RuntimeError(
        "MO DB credentials missing: set MO_DB_* env vars or a `# MO DB UAT` "
        f"block in {ENV}"
    )


def connect():
    """Return a psycopg2 connection to the Middle Office Postgres DB."""
    c = creds()
    return psycopg2.connect(
        host=c["host"],
        port=int(c.get("port", "5432")),
        dbname=c["database"],
        user=c["username"],
        password=c["password"],
        connect_timeout=15,
    )
