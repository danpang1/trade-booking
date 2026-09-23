"""Connector for the tech-team Postgres (prod `production` / uat `uat`).

This is the SAME store as `fee_event` (the one nx-hft-position reads), NOT the
MO DB that holds trades_spot/trades_cashflow. It is the target for the
manual_trade / manual_cashflow dual-write sink.

Mirrors cashflow_db's cred/connection convention, but with a `TECH_DB_*` env
prefix and a `# TECH DB` .env block, so the manual-booking write path never
shares creds or a connection with the existing trades_* wiring.
"""
from __future__ import annotations
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENV = REPO / ".env"

_MARKER = "TECH DB"
_PREFIX = "tech_db_"


def load_creds() -> dict[str, str]:
    """Load tech-DB creds, env vars taking precedence over the .env file.

    Env vars (used in k8s): TECH_DB_HOST, TECH_DB_PORT, TECH_DB_DATABASE,
    TECH_DB_USERNAME, TECH_DB_PASSWORD. If host/database/username/password are
    all present (port defaults to 5432), the .env file is not read at all.

    .env fallback (local dev): parses the `# TECH DB` block — starts at the
    marker, ends at the next `#` comment that isn't the marker or at EOF. Keys
    are lowercased and any `tech_db_` prefix stripped, so both
    ``TECH_DB_HOST: ...`` and ``host: ...`` produce the same dict.
    """
    env_creds = {
        k: os.environ[f"TECH_DB_{k.upper()}"]
        for k in ("host", "port", "database", "username", "password")
        if f"TECH_DB_{k.upper()}" in os.environ
    }
    if all(k in env_creds for k in ("host", "database", "username", "password")):
        env_creds.setdefault("port", "5432")
        return env_creds

    if not ENV.exists():
        raise FileNotFoundError(
            f".env not found at {ENV} and TECH_DB_* env vars are incomplete"
        )

    creds: dict[str, str] = {}
    in_block = False
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if _MARKER in s.upper():
            in_block = True
            continue
        if not in_block:
            continue
        if not s or s.startswith("#"):
            if s.startswith("#") and _MARKER not in s.upper():
                break
            continue
        if ":" in s:
            k, _, v = s.partition(":")
            key = k.strip().lower()
            if key.startswith(_PREFIX):
                key = key[len(_PREFIX):]
            creds[key] = v.strip()

    if not creds:
        raise RuntimeError(f"No '# TECH DB' block (or empty block) found in {ENV}")
    return creds


def configured() -> bool:
    """True if the tech DB is reachable-by-config: TECH_DB_URL (full DSN) or the
    split TECH_DB_* / `# TECH DB` creds. Cheap (no connection) — lets the manual
    dual-write decide whether to run."""
    if os.environ.get("TECH_DB_URL"):
        return True
    try:
        load_creds()
        return True
    except Exception:
        return False


def connect():
    """Open a psycopg2 connection to the tech DB (autocommit off; caller manages txns).

    Accepts a full DSN via `TECH_DB_URL` (matches the k8s `tech-db-config`
    secret's single `url` field) OR the split `TECH_DB_*` / `# TECH DB` creds.
    NOTE: in a libpq URI the password must be percent-encoded — a literal `@`
    is `%40` (e.g. `Password@12345` -> `Password%4012345`).

    Pins the session timezone to UTC so TIMESTAMPTZ values render at +00.
    """
    import psycopg2  # imported here so tests don't require psycopg2

    url = os.environ.get("TECH_DB_URL")
    if url:
        conn = psycopg2.connect(url, connect_timeout=15)
    else:
        c = load_creds()
        conn = psycopg2.connect(
            host=c["host"],
            port=int(c.get("port", "5432")),
            dbname=c["database"],
            user=c["username"],
            password=c["password"],
            connect_timeout=15,
        )
    with conn.cursor() as cur:
        cur.execute("SET TIMEZONE = 'UTC'")
    conn.commit()
    return conn
