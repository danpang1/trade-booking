"""End-to-end smoke for the API tokens surface.

Run server.js separately first:

    node server.js

Then in another terminal:

    python scripts/smoke_tokens.py --username <you> --password <yourpw>

Exits 0 with "PASS" if every assertion passes; non-zero on first failure.
Creates a token (random name, safe to re-run), then revokes it.
"""
from __future__ import annotations
import argparse
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request
import uuid


BASE = "http://localhost:5181"


def _req(method, path, body=None, jar=None, bearer=None):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar or http.cookiejar.CookieJar())
    )
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
    p.add_argument("--base-url", default=BASE)
    args = p.parse_args()

    global BASE
    BASE = args.base_url

    jar = http.cookiejar.CookieJar()
    test_name = f"smoke-{uuid.uuid4().hex[:8]}"

    # 1. Log in to get a session cookie
    status, body = _req("POST", "/api/auth/login",
                        {"username": args.username, "password": args.password}, jar=jar)
    assert status == 200 and body and body.get("user"), f"login failed: {status} {body}"
    print("✓ login (cookie)")

    # 2. Create a token via cookie
    status, body = _req("POST", "/api/tokens",
                        {"name": test_name, "expires_in_days": 30}, jar=jar)
    assert status == 200 and body and body.get("ok"), f"create failed: {status} {body}"
    token = body["token"]
    token_id = body["row"]["id"]
    assert token.startswith("tkmo_") and len(token) == 48, f"bad token format: {token}"
    print(f"✓ create token (id={token_id}, prefix={body['row']['token_prefix']})")

    # 3. List tokens — should include the new one
    status, body = _req("GET", "/api/tokens", jar=jar)
    assert status == 200 and body and body.get("ok"), f"list failed: {status} {body}"
    found = [t for t in body["tokens"] if t["id"] == token_id]
    assert found, f"created token not in list: {body['tokens']}"
    assert "token_hash" not in found[0], "token_hash must NEVER appear in list output"
    print(f"✓ list tokens ({len(body['tokens'])} total)")

    # 4. Use the Bearer token (no cookie this time)
    status, body = _req("GET", "/api/auth/whoami", bearer=token)
    assert status == 200 and body and body.get("user"), f"bearer whoami failed: {status} {body}"
    assert body["user"]["username"].lower() == args.username.lower(), \
        f"bearer resolved to wrong user: {body}"
    print("✓ bearer auth against /api/auth/whoami")

    # 5. Bearer CANNOT mint another token (must be cookie)
    status, body = _req("POST", "/api/tokens",
                        {"name": "should-fail", "expires_in_days": 30}, bearer=token)
    assert status == 403, f"expected 403 when minting via Bearer, got {status} {body}"
    print("✓ bearer blocked from /api/tokens (403)")

    # 6. Revoke (via cookie)
    status, body = _req("DELETE", f"/api/tokens/{token_id}", jar=jar)
    assert status == 200 and body and body.get("ok"), f"revoke failed: {status} {body}"
    print(f"✓ revoke token (id={token_id})")

    # 7. Bearer now fails 401
    status, body = _req("GET", "/api/auth/whoami", bearer=token)
    assert status == 401, f"expected 401 after revoke, got {status} {body}"
    print("✓ revoked token returns 401")

    print("\nPASS")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as e:
        print(f"\nFAIL: {e}", file=sys.stderr)
        sys.exit(1)
