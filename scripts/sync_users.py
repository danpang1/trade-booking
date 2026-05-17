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
from pathlib import Path

import pymysql

REPO = Path(__file__).resolve().parents[2]
ENV = REPO / ".env"
OUT = REPO / "trade-booking" / "public" / "refdata" / "users.json"


def _load_mysql_creds() -> dict[str, str]:
    if not ENV.exists():
        raise FileNotFoundError(f".env not found at {ENV}")
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
    print(f"wrote {len(rows)} superadmin users → {OUT}")


if __name__ == "__main__":
    main()
