"""End-to-end smoke for the Phase 1a drafts surface (CASHFLOW only).

Run the server first:
    node server.js

Then:
    python scripts/smoke_drafts.py --username <you> --password <yourpw>

Exits 0 with "PASS" on success; non-zero with "FAIL: ..." on first failure.
Inserts real rows into trades_cashflow on approve — uses external_trade_id
prefix "SMOKE-DRAFTS-<uuid>" so cleanup is `DELETE ... WHERE external_trade_id LIKE 'SMOKE-DRAFTS-%'`.
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


def _req(method, path, body=None, jar=None):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
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


def _cashflow_payload(label):
    return {
        "cashflow_type": "OTHER INCOME",
        "direction": "INCOMING",
        "entity": "TK006",
        "portfolio_id": 8006,
        "portfolio_name": "CDA",
        "counterparty": "Galaxy",
        "account": "SMOKE_TEST_WALLET",
        "asset": "USDC",
        "amount": "1.00",
        "trade_date": "2026-05-25T12:00:00+00:00",
        "value_date": "2026-05-25T12:00:00+00:00",
        "external_trade_id": f"SMOKE-DRAFTS-{label}",
        "user_id": "placeholder",
        "status": "PENDING",
        "comment": "smoke_drafts.py — safe to delete",
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--username", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--base-url", default=BASE)
    args = p.parse_args()

    global BASE
    BASE = args.base_url

    jar = http.cookiejar.CookieJar()
    run_id = uuid.uuid4().hex[:8]

    # 1. Login
    s, b = _req("POST", "/api/auth/login",
                {"username": args.username, "password": args.password}, jar=jar)
    assert s == 200 and b and b.get("user"), f"login failed: {s} {b}"
    print("✓ login (cookie)")

    # 2. POST /api/bookings/draft (single)
    crid1 = str(uuid.uuid4())
    s, b = _req("POST", "/api/bookings/draft",
                {"category": "CASHFLOW", "client_request_id": crid1,
                 "payload": _cashflow_payload(f"{run_id}-S1")}, jar=jar)
    assert s == 200 and b and b.get("ok"), f"single insert failed: {s} {b}"
    single_id = b["row"]["id"]
    assert b["deduped"] is False
    print(f"✓ POST /draft (id={single_id})")

    # 2b. Dedupe: same client_request_id returns same row
    s, b = _req("POST", "/api/bookings/draft",
                {"category": "CASHFLOW", "client_request_id": crid1,
                 "payload": _cashflow_payload(f"{run_id}-S1-RETRY")}, jar=jar)
    assert s == 200 and b and b.get("ok") and b["deduped"] is True
    assert b["row"]["id"] == single_id, "dedupe returned wrong row"
    print("✓ dedupe on client_request_id")

    # 3. POST /api/bookings/draft/batch (3 trades)
    batch_crids = [str(uuid.uuid4()) for _ in range(3)]
    s, b = _req("POST", "/api/bookings/draft/batch", {"trades": [
        {"category": "CASHFLOW", "client_request_id": batch_crids[0], "payload": _cashflow_payload(f"{run_id}-B1")},
        {"category": "CASHFLOW", "client_request_id": batch_crids[1], "payload": _cashflow_payload(f"{run_id}-B2")},
        {"category": "CASHFLOW", "client_request_id": batch_crids[2], "payload": _cashflow_payload(f"{run_id}-B3")},
    ]}, jar=jar)
    assert s == 200 and b and b.get("ok"), f"batch failed: {s} {b}"
    assert b["created"] == 3
    batch_id = b["batch_id"]
    batch_ids = [r["id"] for r in b["rows"]]
    print(f"✓ POST /draft/batch (batch_id={batch_id[:8]}…, 3 drafts)")

    # 4. GET /api/bookings/drafts?status=PENDING_REVIEW — includes our 4
    s, b = _req("GET", "/api/bookings/drafts?status=PENDING_REVIEW", jar=jar)
    assert s == 200 and b and b.get("ok"), f"list failed: {s} {b}"
    ids = {d["id"] for d in b["drafts"]}
    for want in [single_id, *batch_ids]:
        assert want in ids, f"expected draft id {want} in list"
    print(f"✓ GET /drafts?status=PENDING_REVIEW ({len(b['drafts'])} total)")

    # 5. GET /api/bookings/drafts?batch_id=<...> — only the 3
    s, b = _req("GET", f"/api/bookings/drafts?batch_id={batch_id}", jar=jar)
    assert s == 200 and b and b.get("ok")
    assert {d["id"] for d in b["drafts"]} == set(batch_ids), \
        f"batch filter returned wrong rows: {b['drafts']}"
    print("✓ GET /drafts?batch_id=… returns only that batch")

    # 6. GET /api/bookings/drafts/:id
    s, b = _req("GET", f"/api/bookings/drafts/{single_id}", jar=jar)
    assert s == 200 and b and b.get("ok") and b["draft"]["id"] == single_id
    print(f"✓ GET /drafts/{single_id}")

    # 7. PATCH /api/bookings/drafts/:id — bump amount
    new_payload = _cashflow_payload(f"{run_id}-S1-PATCHED")
    new_payload["amount"] = "777.77"
    s, b = _req("PATCH", f"/api/bookings/drafts/{single_id}",
                {"payload": new_payload}, jar=jar)
    assert s == 200 and b and b.get("ok"), f"patch failed: {s} {b}"
    assert b["row"]["payload"]["amount"] == "777.77"
    print(f"✓ PATCH /drafts/{single_id} (amount → 777.77)")

    # 8. POST /api/bookings/drafts/:id/approve — single
    s, b = _req("POST", f"/api/bookings/drafts/{single_id}/approve", jar=jar)
    assert s == 200 and b and b.get("ok"), f"approve failed: {s} {b}"
    deal_ref_single = b["deal_ref"]
    assert deal_ref_single.startswith("MCF"), f"unexpected deal_ref: {deal_ref_single}"
    print(f"✓ POST /drafts/{single_id}/approve → {deal_ref_single}")

    # 8b. Re-approve = 409
    s, b = _req("POST", f"/api/bookings/drafts/{single_id}/approve", jar=jar)
    assert s == 409, f"expected 409 on re-approve, got {s} {b}"
    print("✓ re-approve returns 409")

    # 9. Approve the batch one by one
    deal_refs = []
    for bid in batch_ids:
        s, b = _req("POST", f"/api/bookings/drafts/{bid}/approve", jar=jar)
        assert s == 200 and b and b.get("ok"), f"approve batch row {bid} failed: {s} {b}"
        deal_refs.append(b["deal_ref"])
    print(f"✓ approved batch (deal_refs: {', '.join(deal_refs)})")

    # 10. Reject (insert a fresh pending one first)
    crid_rej = str(uuid.uuid4())
    s, b = _req("POST", "/api/bookings/draft",
                {"category": "CASHFLOW", "client_request_id": crid_rej,
                 "payload": _cashflow_payload(f"{run_id}-REJ")}, jar=jar)
    assert s == 200 and b and b.get("ok")
    rej_id = b["row"]["id"]
    s, b = _req("POST", f"/api/bookings/drafts/{rej_id}/reject",
                {"reason": "smoke test reject"}, jar=jar)
    assert s == 200 and b and b.get("ok") and b["row"]["status"] == "REJECTED"
    print(f"✓ POST /drafts/{rej_id}/reject")

    # 10b. Re-reject = 409
    s, b = _req("POST", f"/api/bookings/drafts/{rej_id}/reject", {}, jar=jar)
    assert s == 409, f"expected 409 on re-reject, got {s} {b}"
    print("✓ re-reject returns 409")

    print("\nPASS")
    print(f"\nCleanup: DELETE FROM trades_cashflow WHERE external_trade_id LIKE 'SMOKE-DRAFTS-{run_id}-%';")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as e:
        print(f"\nFAIL: {e}", file=sys.stderr)
        sys.exit(1)
