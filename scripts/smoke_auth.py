"""End-to-end smoke for the auth surface.

Run server.js separately first:

    node server.js

Then in another terminal:

    python scripts/smoke_auth.py --username peter --password <YOUR_PW>

Exits 0 with "PASS" if every assertion passes. Non-zero on first failure
with a diagnostic. Exercises login/whoami/logout + bad-login + a guarded
/api/users probe. Does not create or delete users.
"""
from __future__ import annotations
import argparse
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request


BASE = "http://localhost:5181"


def _req(method, path, body=None, jar=None):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    try:
        resp = opener.open(req)
        raw = resp.read().decode("utf-8") or "null"
        return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8") or "null"
        return e.code, json.loads(raw) if raw else None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--username", required=True)
    p.add_argument("--password", required=True)
    args = p.parse_args()

    jar = http.cookiejar.CookieJar()

    # 1. Hit /api/auth/me without cookie → 401
    s, _ = _req("GET", "/api/auth/me", jar=jar)
    assert s == 401, f"expected 401 on unauthenticated /me, got {s}"

    # 2. Login
    s, body = _req("POST", "/api/auth/login",
                   {"username": args.username, "password": args.password}, jar)
    assert s == 200 and body and body.get("ok") is True, f"login failed: {s} {body}"
    assert body["user"]["username"] == args.username, body
    role = body["user"]["role"]

    # 3. whoami works
    s, body = _req("GET", "/api/auth/me", jar=jar)
    assert s == 200 and body and body["user"]["username"] == args.username, f"whoami: {s} {body}"

    # 4. /api/users — admin gets 200, non-admin gets 403
    s, body = _req("GET", "/api/users", jar=jar)
    if role == "admin":
        assert s == 200 and body and body.get("ok") is True, f"/api/users as admin: {s} {body}"
    else:
        assert s == 403, f"/api/users as non-admin: expected 403, got {s} {body}"

    # 5. Bad login (separate jar, no cookie)
    s, _ = _req("POST", "/api/auth/login",
                {"username": args.username, "password": "definitely-wrong-pw"})
    assert s == 401, f"expected 401 on bad password, got {s}"

    # 6. Logout
    s, _ = _req("POST", "/api/auth/logout", jar=jar)
    assert s in (200, 204), f"logout: expected 204, got {s}"

    # 7. /me after logout → 401
    s, _ = _req("GET", "/api/auth/me", jar=jar)
    assert s == 401, f"expected 401 after logout, got {s}"

    print("PASS")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
