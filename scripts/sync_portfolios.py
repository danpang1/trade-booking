"""Sync the portfolio reference list from MySQL → JSON file.

Source : sg-ro-mysql.internal.tokkalabs.com, `reference_data.portfolio`
Target : trade-booking/public/refdata/portfolios.json
Filter : deletedAt IS NULL AND (status IS NULL OR status='ACTIVE')

The React form (TradeBookingForm.jsx) fetches the JSON on mount and
on refresh-button click, replacing the historic hardcoded PORTFOLIOS
constant.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pymysql

REPO = Path(__file__).resolve().parents[1]
ENV = REPO / ".env"
OUT = REPO / "public" / "refdata" / "portfolios.json"


def _load_mysql_creds() -> dict[str, str]:
    """Env vars (SG_RO_MYSQL_*) take precedence; .env file parsed as fallback."""
    env_creds = {
        k: os.environ[f"SG_RO_MYSQL_{k.upper()}"]
        for k in ("host", "username", "password")
        if f"SG_RO_MYSQL_{k.upper()}" in os.environ
    }
    if all(k in env_creds for k in ("host", "username", "password")):
        return env_creds

    if not ENV.exists():
        raise FileNotFoundError(
            f".env not found at {ENV} and SG_RO_MYSQL_* env vars are incomplete"
        )

    lines = ENV.read_text(encoding="utf-8", errors="replace").splitlines()
    creds: dict[str, str] = {}
    for i, ln in enumerate(lines):
        if "sg-ro-mysql" in ln.lower():
            for j in range(max(0, i - 5), min(len(lines), i + 3)):
                s = lines[j].strip()
                if not s or s.startswith("#"):
                    continue
                if ":" in s:
                    k, _, v = s.partition(":")
                    creds[k.strip().lower()] = v.strip()
            break
    if not all(k in creds for k in ("username", "password", "host")):
        raise RuntimeError("sg-ro-mysql credentials missing in .env")
    return creds


def main() -> None:
    creds = _load_mysql_creds()
    conn = pymysql.connect(
        host=creds["host"],
        user=creds["username"],
        password=creds["password"],
        database="reference_data",
        connect_timeout=15,
    )
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, number, name, organisation, type, mainGroup, manager "
            "FROM portfolio "
            "WHERE deletedAt IS NULL AND (status IS NULL OR status='ACTIVE') "
            "ORDER BY number"
        )
        rows = [
            {
                "id": r[0],
                "number": r[1],
                "name": r[2],
                "entity": r[3],
                "type": r[4],
                "mainGroup": r[5],
                "manager": r[6],
            }
            for r in cur.fetchall()
        ]
    finally:
        conn.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} portfolios -> {OUT}")


if __name__ == "__main__":
    main()
