"""End-to-end smoke for the auth surface.

Run server.js separately first:

    node server.js

Then in another terminal:

    python scripts/smoke_auth.py --username peter --password <YOUR_PW>

Add --register to also exercise the public registration + admin approval flow:

    python scripts/smoke_auth.py --username peter --password <YOUR_PW> --register

Exits 0 with "PASS" if every assertion passes. Non-zero on first failure
with a diagnostic. Existing checks: login/whoami/logout + bad-login + a
guarded /api/users probe. Does not create or delete users (admin smoke).

--register mode adds: register → pending-login fails → approve → login OK
→ register → reject → login fails. Cleans up the approved test user
via the existing DELETE endpoint. Uses a randomized username so it's
safe to re-run without DB cleanup.
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
    p.add_argument("--username", required=True, help="Admin username (for approve/reject steps)")
    p.add_argument("--password", required=True, help="Admin password")
    p.add_argument("--register", action="store_true",
                   help="Additionally exercise the public registration + approve/reject flow")
    p.add_argument("--base-url", default=BASE,
                   help=f"Base URL of the running server (default {BASE})")
    args = p.parse_args()

    # Allow --base-url to override the module constant for this run
    global BASE
    BASE = args.base_url

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

    if args.register:
        import random
        import string
        if role != "admin":
            print("FAIL: --register requires an admin account; passed user is not admin",
                  file=sys.stderr)
            return 1

        uname = "smoke_reg_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        email = f"{uname}@smoke.test"
        pw = "Secret-12345"
        admin_jar = jar  # existing admin session

        # 4a. Register fresh user (public endpoint, separate cookie jar)
        s, body = _req("POST", "/api/auth/register",
                       {"username": uname, "email": email, "password": pw})
        assert s == 200 and body and body.get("ok") is True, \
            f"register failed: {s} {body}"
        user_id = body["user"]["id"]
        assert body["user"]["status"] == "pending", f"new user status: {body['user']}"
        assert body["user"]["role"] is None, f"new user role should be null: {body['user']}"

        # 4b. Login with the new account while pending → expect 401 with the pending message
        s, body = _req("POST", "/api/auth/login", {"username": uname, "password": pw})
        assert s == 401, f"pending login: expected 401, got {s} {body}"
        assert body and "pending" in (body.get("error") or "").lower(), \
            f"pending login error: {body}"

        # 4c. Admin approves the new user as 'user'
        s, body = _req("POST", f"/api/users/{user_id}/approve",
                       {"role": "user"}, jar=admin_jar)
        assert s == 200 and body and body.get("ok") is True, \
            f"approve failed: {s} {body}"
        assert body["user"]["status"] == "active", f"post-approve status: {body['user']}"
        assert body["user"]["role"] == "user", f"post-approve role: {body['user']}"

        # 4d. Login as the new user → expect 200
        s, body = _req("POST", "/api/auth/login", {"username": uname, "password": pw})
        assert s == 200 and body and body.get("ok") is True, \
            f"post-approve login: {s} {body}"

        # 4e. Register a second user → admin rejects → login should fail
        uname2 = uname + "_b"
        s, body = _req("POST", "/api/auth/register",
                       {"username": uname2, "email": f"{uname2}@smoke.test", "password": pw})
        assert s == 200 and body and body.get("ok") is True, \
            f"second register: {s} {body}"
        uid2 = body["user"]["id"]

        s, body = _req("POST", f"/api/users/{uid2}/reject", jar=admin_jar)
        assert s == 200 and body and body.get("ok") is True, \
            f"reject failed: {s} {body}"

        s, body = _req("POST", "/api/auth/login", {"username": uname2, "password": pw})
        assert s == 401, f"post-reject login: expected 401, got {s} {body}"
        assert body and "invalid" in (body.get("error") or "").lower(), \
            f"post-reject error should be 'invalid credentials': {body}"

        # 4f. Clean up the approved user (the rejected one is already gone)
        #     Use the existing /api/users/:id DELETE endpoint via the admin jar.
        s, _ = _req("DELETE", f"/api/users/{user_id}", jar=admin_jar)
        assert s == 200, f"cleanup delete: {s}"

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
