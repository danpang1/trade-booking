// Portfolio scoping decisions for server.js.
//
// Extracted so the route table can be tested without standing up a server:
// the classifier is the piece where a mistake is silent, so it is the piece
// that most needs a test.
//
// Lives at the repo root next to server.js and is COPYed into the prod image
// alongside it — see docker/Dockerfile.

// Past this age the access map is not trustworthy and non-admins are denied.
// Long enough that an overnight blip doesn't page anyone, short enough that a
// revoked access can't outlive a working day.
export const ACCESS_STALE_MAX_MS = 12 * 60 * 60 * 1000;
export const ACCESS_RETRY_MS = 10 * 60 * 1000;

// Every /api/* path is declared here. An UNDECLARED path classifies as
// admin-only: server.js grows a route every few commits, and under an
// allow-by-default scheme the cost of forgetting one is a silent data leak,
// where deny-by-default costs a 403 that gets reported the same day.
//
// Ordered — first match wins, so more specific patterns come first.
export const ROUTE_RULES = [
  // public: handled before the auth gate, listed for completeness
  [/^\/api\/health$/, "*", "public"],
  [/^\/api\/auth\/(login|register)$/, "POST", "public"],

  // self-referential
  [/^\/api\/auth\/(me|logout)$/, "*", "unscoped"],

  // admin surfaces
  [/^\/api\/users(\/|$)/, "*", "admin-only"],
  [/^\/api\/tokens(\/|$)/, "*", "admin-only"],
  [/^\/api\/binance\//, "*", "admin-only"],
  [/^\/api\/funding\/settings$/, "POST", "admin-only"],

  // drafts: approval is the authority and stays admin-only, but the list and
  // single-get are scoped so the tokka-mo plugin keeps working.
  [/^\/api\/bookings\/drafts\/\d+\/(approve|reject)$/, "POST", "admin-only"],
  [/^\/api\/bookings\/drafts\/\d+$/, "PATCH", "scoped-write"],
  [/^\/api\/bookings\/drafts(\/\d+)?\/?$/, "GET", "scoped-read"],
  [/^\/api\/bookings\/draft(\/batch)?$/, "POST", "scoped-write"],

  // refdata + market data disclose nothing portfolio-specific
  [/^\/api\/(refdata\/refresh|refresh)$/, "POST", "unscoped"],
  [/^\/api\/rates\/latest/, "GET", "unscoped"],
  [/^\/api\/funding\/settings$/, "GET", "unscoped"],
  [/^\/api\/cashflow\/fetch-tx$/, "POST", "unscoped"],

  // the books
  [/^\/api\/(cashflow|loan|spot)\/(insert|amend)(\/batch)?$/, "POST", "scoped-write"],
  [/^\/api\/loan\/schedule-comment$/, "POST", "scoped-write"],
  [/^\/api\/(cashflow|loan|spot)\/recent/, "GET", "scoped-read"],
  [/^\/api\/loan\/export/, "GET", "scoped-read"],
  [/^\/api\/exports\/blotter\.csv/, "*", "scoped-read"],
  [/^\/api\/(cashflow|loan|spot)\/[^/]+(\/history)?$/, "GET", "scoped-read"],
];

export function classifyRoute(method, pathname) {
  for (const [pattern, verb, klass] of ROUTE_RULES) {
    if (verb !== "*" && verb !== method) continue;
    if (pattern.test(pathname)) return klass;
  }
  return "admin-only";  // deny by default
}

// The single scope decision. Everything downstream consumes its result.
//
// An admin is answered without consulting the map at all, so a refdata outage
// never locks out the people who would have to fix it. That is the deliberate
// break-glass path.
//
// `accessMap` is {byEmail: Map, loadedAt: number|null}.
export function scopeFor(sessionUser, accessMap, now = Date.now()) {
  if (sessionUser && sessionUser.role === "admin") return { kind: "all" };
  const age = accessMap.loadedAt === null
    ? Number.POSITIVE_INFINITY
    : now - accessMap.loadedAt;
  if (age > ACCESS_STALE_MAX_MS) return { kind: "deny" };
  const email = ((sessionUser && sessionUser.email) || "").trim().toLowerCase();
  return { kind: "scoped", portfolios: accessMap.byEmail.get(email) || [] };
}

// Inject the scope into the JSON a Python script reads on stdin. Admins and
// unscoped routes pass nothing, so the scripts read an absent `_scope` as
// "no filter" and a present one as the whole allowed set.
export function withScope(req, obj) {
  const scope = req.scope;
  if (scope && scope.kind === "scoped") obj._scope = scope.portfolios;
  return JSON.stringify(obj);
}

// Same, for a raw request body passed through to Python verbatim.
export function stampScope(rawBody, req) {
  const scope = req.scope;
  if (!scope || scope.kind !== "scoped") return rawBody;
  let payload;
  try { payload = JSON.parse(rawBody || "{}"); }
  catch { return rawBody; }  // let Python report the bad-JSON error
  if (payload && typeof payload === "object") payload._scope = scope.portfolios;
  return JSON.stringify(payload);
}
