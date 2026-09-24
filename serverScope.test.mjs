// Standalone test for the portfolio scope classifier and decision function.
// Run: node serverScope.test.mjs
// Exits non-zero on the first failed assertion.
import {
  ACCESS_STALE_MAX_MS, classifyRoute, scopeFor, withScope, stampScope,
} from "./serverScope.mjs";

let failures = 0;
function check(name, cond) {
  if (cond) console.log(`ok   - ${name}`);
  else { failures += 1; console.error(`FAIL - ${name}`); }
}
function eq(name, got, want) {
  check(`${name} (got ${JSON.stringify(got)})`, got === want);
}

// ── deny by default ───────────────────────────────────────────────
// The point of the whole table: a route nobody classified must not serve
// a normal user.
eq("an undeclared route defaults to admin-only",
  classifyRoute("GET", "/api/some/route/added/next/quarter"), "admin-only");
eq("an undeclared POST defaults to admin-only",
  classifyRoute("POST", "/api/positions"), "admin-only");
eq("a declared path under the wrong verb still defaults to admin-only",
  classifyRoute("DELETE", "/api/cashflow/recent"), "admin-only");

// ── the books are scoped ──────────────────────────────────────────
for (const kind of ["cashflow", "loan", "spot"]) {
  eq(`${kind}/recent is scoped-read`,
    classifyRoute("GET", `/api/${kind}/recent`), "scoped-read");
  eq(`${kind} single deal is scoped-read`,
    classifyRoute("GET", `/api/${kind}/MCF00000042`), "scoped-read");
  eq(`${kind} history is scoped-read`,
    classifyRoute("GET", `/api/${kind}/MCF00000042/history`), "scoped-read");
  eq(`${kind}/insert is scoped-write`,
    classifyRoute("POST", `/api/${kind}/insert`), "scoped-write");
  eq(`${kind}/amend is scoped-write`,
    classifyRoute("POST", `/api/${kind}/amend`), "scoped-write");
  eq(`${kind}/amend/batch is scoped-write`,
    classifyRoute("POST", `/api/${kind}/amend/batch`), "scoped-write");
}

// ── exports: the easiest surface to forget, the worst to leak ──────
eq("blotter.csv is scoped-read",
  classifyRoute("GET", "/api/exports/blotter.csv"), "scoped-read");
eq("blotter.csv HEAD is scoped-read too",
  classifyRoute("HEAD", "/api/exports/blotter.csv"), "scoped-read");
eq("loan export is scoped-read",
  classifyRoute("GET", "/api/loan/export"), "scoped-read");

// ── drafts ────────────────────────────────────────────────────────
eq("draft list is scoped-read (the plugin reads it)",
  classifyRoute("GET", "/api/bookings/drafts"), "scoped-read");
eq("draft single get is scoped-read",
  classifyRoute("GET", "/api/bookings/drafts/42"), "scoped-read");
eq("draft create is scoped-write",
  classifyRoute("POST", "/api/bookings/draft"), "scoped-write");
eq("draft batch create is scoped-write",
  classifyRoute("POST", "/api/bookings/draft/batch"), "scoped-write");
eq("draft patch is scoped-write",
  classifyRoute("PATCH", "/api/bookings/drafts/42"), "scoped-write");
eq("draft approve is admin-only — approval is the authority",
  classifyRoute("POST", "/api/bookings/drafts/42/approve"), "admin-only");
eq("draft reject is admin-only",
  classifyRoute("POST", "/api/bookings/drafts/42/reject"), "admin-only");

// ── admin surfaces ────────────────────────────────────────────────
eq("users list is admin-only", classifyRoute("GET", "/api/users"), "admin-only");
eq("user approve is admin-only",
  classifyRoute("POST", "/api/users/7/approve"), "admin-only");
eq("token mint is admin-only", classifyRoute("POST", "/api/tokens"), "admin-only");
eq("token revoke is admin-only",
  classifyRoute("DELETE", "/api/tokens/3"), "admin-only");
eq("binance proxy is admin-only",
  classifyRoute("GET", "/api/binance/proxy"), "admin-only");
eq("binance vip-loan ltv is admin-only",
  classifyRoute("GET", "/api/binance/vip-loan/ltv"), "admin-only");
eq("funding settings write is admin-only",
  classifyRoute("POST", "/api/funding/settings"), "admin-only");

// ── unscoped ──────────────────────────────────────────────────────
eq("whoami is unscoped", classifyRoute("GET", "/api/auth/me"), "unscoped");
eq("refdata refresh is unscoped",
  classifyRoute("POST", "/api/refdata/refresh"), "unscoped");
eq("rates are unscoped", classifyRoute("GET", "/api/rates/latest"), "unscoped");
eq("funding settings read is unscoped",
  classifyRoute("GET", "/api/funding/settings"), "unscoped");
eq("tx fetch is unscoped",
  classifyRoute("POST", "/api/cashflow/fetch-tx"), "unscoped");
check("tx fetch is not swallowed by the single-deal pattern",
  classifyRoute("POST", "/api/cashflow/fetch-tx") !== "scoped-read");

// ── scopeFor ──────────────────────────────────────────────────────
const warm = { byEmail: new Map([["francis@x.com", [8041, 8043]]]), loadedAt: Date.now() };
const cold = { byEmail: new Map(), loadedAt: null };
const stale = {
  byEmail: new Map([["francis@x.com", [8041]]]),
  loadedAt: Date.now() - ACCESS_STALE_MAX_MS - 1000,
};
const admin = { role: "admin", email: "danny@x.com" };
const user = { role: "user", email: "francis@x.com" };
const orphan = { role: "user", email: "nobody@x.com" };

eq("an admin is unfiltered", scopeFor(admin, warm).kind, "all");
eq("an admin is unaffected by a cold map — the break-glass path",
  scopeFor(admin, cold).kind, "all");
eq("an admin is unaffected by a stale map",
  scopeFor(admin, stale).kind, "all");

eq("a user on a warm map is scoped", scopeFor(user, warm).kind, "scoped");
check("a user gets exactly their portfolios",
  JSON.stringify(scopeFor(user, warm).portfolios) === "[8041,8043]");

eq("a cold map denies a non-admin", scopeFor(user, cold).kind, "deny");
eq("a stale map denies a non-admin", scopeFor(user, stale).kind, "deny");

eq("a user in no portfolio is scoped, not denied",
  scopeFor(orphan, warm).kind, "scoped");
check("...and that scope is empty, which filters everything out",
  scopeFor(orphan, warm).portfolios.length === 0);

eq("email matching is case- and space-insensitive",
  scopeFor({ role: "user", email: "  Francis@X.com " }, warm).portfolios.length, 2);

// ── withScope / stampScope ────────────────────────────────────────
const scopedReq = { scope: { kind: "scoped", portfolios: [8041] } };
const adminReq = { scope: { kind: "all" } };

check("withScope injects _scope for a scoped caller",
  JSON.parse(withScope(scopedReq, { limit: 20 }))._scope[0] === 8041);
check("withScope injects nothing for an admin",
  JSON.parse(withScope(adminReq, { limit: 20 }))._scope === undefined);
check("stampScope injects _scope into a raw body",
  JSON.parse(stampScope('{"deal_ref":"X"}', scopedReq))._scope[0] === 8041);
check("stampScope leaves an admin body untouched",
  stampScope('{"deal_ref":"X"}', adminReq) === '{"deal_ref":"X"}');
check("stampScope passes malformed JSON through for Python to report",
  stampScope("not json", scopedReq) === "not json");

console.log(failures === 0 ? "\nALL PASS" : `\n${failures} FAILURE(S)`);
process.exit(failures === 0 ? 0 : 1);
