"""Sync the booking-user list from MySQL → JSON file.

Source : sg-ro-mysql.internal.tokkalabs.com, `reference_data.user`
Target : trade-booking/public/refdata/users.json
Filter : isActive=1 AND roleName='superadmin'
         (only superadmins can book trades; broaden the filter if MO
         policy changes — adjust the WHERE clause below.)

The React form (TradeBookingForm.jsx) fetches the JSON on mount and
on refresh-button click, replacing the historic hardcoded
SUPERADMIN_USERS + USER_PROFILES constants.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pymysql

REPO = Path(__file__).resolve().parents[1]
ENV = REPO / ".env"
OUT = REPO / "public" / "refdata" / "users.json"


def _load_mysql_creds() -> dict[str, str]:
    """Env vars (T2X_RO_MYSQL_*) take precedence; .env file parsed as fallback."""
    env_creds = {
        k: os.environ[f"T2X_RO_MYSQL_{k.upper()}"]
        for k in ("host", "username", "password")
        if f"T2X_RO_MYSQL_{k.upper()}" in os.environ
    }
    if all(k in env_creds for k in ("host", "username", "password")):
        return env_creds

    if not ENV.exists():
        raise FileNotFoundError(
            f".env not found at {ENV} and T2X_RO_MYSQL_* env vars are incomplete"
        )
    lines = ENV.read_text(encoding="utf-8", errors="replace").splitlines()
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
    if not all(k in creds for k in ("username", "password", "host")):
        raise RuntimeError("t2x-ro-mysql credentials missing in .env")
    return creds


def _title_case_username(username: str) -> str:
    """`danny.pang` → `Danny Pang`."""
    return " ".join(part.capitalize() for part in username.replace(".", " ").split())


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
            "SELECT id, name, email, roleName FROM user "
            "WHERE deletedAt IS NULL AND isActive=1 AND roleName='superadmin' "
            "ORDER BY name"
        )
        rows = [
            {
                "id": r[0],
                "username": r[1],
                "displayName": _title_case_username(r[1]),
                "email": r[2],
                "roleName": r[3],
            }
            for r in cur.fetchall()
        ]
    finally:
        conn.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} superadmin users -> {OUT}")


if __name__ == "__main__":
    main()
