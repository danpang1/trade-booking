# Portfolio-scoped access control

**Date:** 2026-09-23
**Status:** Design approved, not yet implemented

## Problem

Every authenticated TMS user currently sees every deal in every portfolio, and
every page. There is no notion of whose book a row belongs to.

We want:

- A non-admin user sees only the trades and loans of the portfolios they own.
- A non-admin user sees only two surfaces: Create Deal and Deal Enquiry.
- An admin sees all pages and all portfolios, as today.
- Ownership is decided by T2X, not by a list maintained inside TMS.

## Source of truth

`reference_data.portfolio.usernames` on the T2X read-only MySQL is a
comma-separated list of emails per portfolio, maintained in TMS by the desk. It
is the firm's own answer to "whose book is this", so it is the right thing to
gate on: there is no second list to keep in step, and granting someone a
portfolio in T2X grants them TMS access with no deploy.

A TMS login is matched to it by `users.email` (Postgres) against that list,
case-insensitively.

Three in-house implementations of this same lookup already exist and agree on
the semantics: `ace-run/access.py` (with tests), `Paxos mintburn/access.py`, and
`slack-trade-bot/access.py`. This design follows them.

**Admin is NOT sourced from T2X.** It stays `users.role = 'admin'` in Postgres,
which is what the code already gates on and what the Users page already
controls. T2X only ever supplies the portfolio list for non-admins.

## Component 1 - `scripts/portfolio_access.py`

A new sibling of the three existing `access.py` modules, trimmed to what TMS
needs: no account/wallet resolution, no T2X role.

Query:

```sql
SELECT number, name, usernames FROM portfolio
 WHERE deletedAt IS NULL
   AND (status IS NULL OR status <> 'DELETED')
```

Semantics, each one load-bearing:

- `deletedAt IS NULL` - a soft-deleted portfolio still carries its old
  `usernames`. Reading it would keep granting access to a book MO has retired.
  `ace-run/tests/test_access.py` has a regression test for exactly this.
- Only `DELETED` is excluded from `status`, **not** `DORMANT`. A dormant
  portfolio is a live grant; it simply is not trading today.
- Emails are trimmed and lowercased on both sides.
- If no portfolio has any `usernames` at all, the module raises rather than
  returning an empty map. A successful query against broken or empty refdata
  would otherwise read as "nobody has access to anything" and lock the firm out.

Credentials come from `T2X_RO_MYSQL_{HOST,USERNAME,PASSWORD}`, falling back to
the `.env` block, exactly as `sync_portfolios.py` does today. No new secret.

Output is JSON on stdout:

```json
{"ok": true,
 "generated_at": "<iso8601>",
 "by_email": {"francis.x@tokkalabs.com": [8041, 8043]},
 "names": {"8041": "TOKKA LABS - ..."}}
```

It writes **nothing to disk**. In particular it must never write to
`public/refdata/`, which is served to browsers without authentication - the
firm's email-to-book map is not a static asset.

### `--audit` mode

A read-only report: every TMS user, their email, their role, and the portfolios
T2X would grant them. Not a runtime dependency and not a kill switch. It exists
to answer, before deploying, whether the answer is "fine" or "the bot and four
traders go dark".

## Component 2 - the cache in `server.js`

In-memory `{byEmail, names, loadedAt}`.

Warming reuses machinery that already exists: the server pod is already given
`T2X_RO_MYSQL_*` via `helm_values/base.yaml`, and `server.js` already runs
`runAllSyncs` at startup and on an hourly tick. The access map joins that tick.
A refresh failure keeps the last good copy and retries every 10 minutes while
the map is cold or stale.

Staleness ceiling: **12 hours**. Long enough that an overnight blip does not
page anyone, short enough that a revoked access cannot outlive a working day.

### `scopeFor(sessionUser)`

The single decision function. Everything else consumes its result.

| Condition | Result | Behaviour |
|---|---|---|
| `role === 'admin'` | `{kind: 'all'}` | Unfiltered. **Never consults the map**, so admins keep working through a refdata outage. Deliberate break-glass path. |
| Cache never loaded, or `loadedAt` older than the ceiling | `{kind: 'deny'}` | `503`, "portfolio access data unavailable" |
| Otherwise | `{kind: 'scoped', portfolios: [...]}` | Filtered |
| ...and the list is empty | `{kind: 'scoped', portfolios: []}` | Reads return zero rows; writes `403` |

The last two rows are deliberately distinct states. "You are in no portfolio" is
an honest empty table. "We cannot tell who you are" is a 503 that says so.
Collapsing them would make a refdata outage look, to a trader, exactly like
their access being revoked.

## Component 3 - route classification

A table near the top of `server.js` declares every `/api/*` path as one of
`public`, `unscoped`, `scoped-read`, `scoped-write`, `admin-only`. The gate runs
once, immediately after `resolveSession()` populates `req.sessionUser`, and
attaches `req.scope`.

**An undeclared path is treated as `admin-only`.** `server.js` is a ~1300-line
if-chain that grows a route every few commits. Under an allow-by-default scheme
the failure mode of forgetting a route is a silent data leak; under
deny-by-default it is a 403 that gets reported the same day.

Classifications that are judgement calls rather than mechanics:

| Route | Class | Rationale |
|---|---|---|
| `/api/bookings/drafts` list + get | scoped-read | The Approvals *page* is hidden from non-admins in the UI, but the plugin's `tokka-mo:drafts` reads this API. Admin-only would break the plugin; scoping keeps it correct. |
| `/api/bookings/drafts/:id/approve` and `/reject` | admin-only | Approval is the actual authority and must not be delegated. |
| `/api/bookings/draft` and `/draft/batch` POST | scoped-write | Portfolio is inside the JSONB payload. |
| `PATCH /api/bookings/drafts/:id` | scoped-write | Edits a draft in place; both-ends rule applies. |
| `/api/tokens` POST/GET/DELETE | admin-only | The page is hidden from non-admins; the API has to follow or the page is decoration. Already-issued tokens keep authenticating - this gates minting only. |
| `/api/binance/proxy`, `/api/binance/vip-loan/*` | admin-only | Firm treasury and LTV data (PTF 8888). Never a per-desk surface. |
| `/api/refdata/refresh`, `/api/refresh` | unscoped | The form's refresh button calls it and it discloses nothing portfolio-specific. |
| `/api/cashflow/fetch-tx`, `/api/rates/latest` | unscoped | On-chain tx lookup and market rates; no portfolio data. |
| `/api/exports/blotter.csv`, `/api/loan/export` | scoped-read | The CSV exports are the easiest surface to forget and the worst to leak. |
| `/api/{cashflow,loan,spot}/recent`, `GET /api/loan/:dealRef` | scoped-read | |
| `/api/{cashflow,loan,spot}/insert`, `/amend`, `/amend/batch` | scoped-write | |
| `/api/loan/schedule-comment` | scoped-write | Addressed by loan `deal_ref`. |
| `/api/funding/settings` GET | unscoped | Global settings, no portfolio data. |
| `/api/funding/settings` POST | admin-only | Writes global settings. |
| `/api/users*` | admin-only | Unchanged from today. |
| `/api/auth/me`, `/logout` | unscoped | Self-referential. |
| `/api/auth/login`, `/register`, `/api/health` | public | Unchanged from today. |

## Component 4 - read scoping

One added predicate in each `*_recent.py` and export script when `_scope` is
present in the stdin JSON:

```sql
AND t.portfolio_id = ANY(%s)     -- scope numbers cast to text
```

`portfolio_id` is `TEXT` holding the portfolio *number* (8041), and is already
indexed on all three tables - `idx_tcf_portfolio`, `idx_tspot_portfolio`, and a
partial `(portfolio_id, trade_date DESC)` on `trades_loan` - so the predicate is
free.

`cashflow_recent.py` additionally LEFT JOINs `loan_cashflow_map`, which can
surface loan `deal_ref`s from portfolios outside scope. That join is filtered in
the same change.

## Component 5 - write scoping

For `insert`, validating the incoming `portfolio_id` against the scope is
sufficient.

For **`amend` it is not.** An amend addresses an existing row by `deal_ref`, so
the script must load that row's current `portfolio_id` and require that **both
the existing and the incoming portfolio are in scope**:

- Checking only the incoming value lets a user pull someone else's deal into
  their own book.
- Checking only the existing value lets a user push their own deal out to a
  portfolio they cannot see.

The same both-ends rule applies to every `deal_ref`-addressed route:
`/api/loan/schedule-comment`, `GET /api/loan/:dealRef`, and
`PATCH /api/bookings/drafts/:id`.

## Component 6 - client

`/api/auth/me` grows to:

```json
{"username": "...", "email": "...", "role": "user",
 "portfolios": [{"number": 8041, "name": "..."}],
 "scope_state": "all"}
```

`scope_state` is one of `all`, `scoped`, `deny`. `AuthContext` exposes the whole
object; every UI decision reads from there rather than re-deriving anything.

These changes are cosmetic - the server is the authority. Their job is to stop
the UI offering actions that would 403.

- Nav renders Create Deal + Deal Enquiry only for non-admins. Loan Enquiry,
  Approvals, Dashboard and API Tokens are hidden. Users is already admin-gated.
- The `appView === ...` **render blocks** get the same guards as the nav items,
  not just the nav. Hiding a tab while leaving its render block reachable is how
  a stale `appView` puts a hidden page on screen.
- `PortfolioPicker` (TradeBookingForm.jsx ~5811) is fed the scoped list, not the
  full `PORTFOLIOS`.
- Deal Enquiry's filter panel defaults to `portfolios: PORTFOLIOS.map(number)`
  (~4714). That must become the scoped list, or the "all portfolios" chip claims
  a breadth the data does not have.
- `scope_state: 'deny'` renders the outage banner in place of an empty table.

## Component 7 - the Colossus bot booking gate

**Repo: `slack-trade-bot`. A separate change from everything above.**

The Colossus bot's Bearer token belongs to **danny.pang**, who must remain a TMS
admin for the bot to function. That makes the bot a full bypass of everything in
this document unless it gates itself.

`bot.py` already gates its *read* paths on the Slack user's own portfolios:

- LTV (~line 2001, via `ltv.allowlist_ready`)
- Binance (~2073, `binance_q.may_see`)
- TMS queries (~2128, `access.portfolios_for`, returning `tms.no_access_text()`
  for a user in no portfolio)

The **booking** handler (~2581 and ~2902, through `resolve_booking_user` ->
`validate_trades` -> draft insert) calls `access.*` nowhere. It resolves the
Slack user's email only to stamp `booking_user` and `requested_by`, never to
check whether they may book that portfolio.

The effect, once TMS scoping ships: a trader who cannot see PTF 8043 in the
dashboard can @mention Colossus and book into 8043, because the submission
carries danny.pang's admin token. The dashboard control would be real for
reading and hollow for writing.

**Fix:** before submitting, check every trade's `portfolio_id` against
`access.portfolios_for(<slack user email>)` and reject the booking if any leg
falls outside it. Reuses the already-warm `access.py` and follows the same
shape as the TMS-query gate, including its refdata-unavailable message.

Notes:

- Inter-PTF funding books **two legs in different portfolios**. The requester
  must own both, or the booking is refused - not silently half-booked.
- A Slack profile with no readable email already degrades to a
  `BOOKING_USER_PREFIX + slack_id` stamp. With no email there is no portfolio
  list, so that case must now be refused rather than booked unscoped.

A follow-up, not in this change: make TMS honour `requested_by`, so an admin
Bearer token supplying it is scoped to *that* user's portfolios. That closes the
same hole from the server end. It is defence-in-depth rather than the primary
fix, because a caller can omit `requested_by` and get admin scope back.

## Blast radius

Rollout is a hard ship - no feature flag, enforced from the first deploy. Two
things are most likely to bite:

1. **The Colossus bot.** Its token belongs to danny.pang, so the bot keeps
   working **provided danny.pang is `role = 'admin'` in the TMS Postgres
   `users` table** - confirm before deploying. Component 7 is what stops that
   admin token becoming a hole.
2. **Existing non-admins.** Anyone whose email is not in a `portfolio.usernames`
   goes from seeing everything to an empty table and four fewer pages.

`portfolio_access.py --audit` is the pre-deploy check for both.

## Testing

pytest under `tests/`, importing from `scripts/` as the existing tests do.

Ported from `ace-run/tests/test_access.py`, which already proves these:

- a soft-deleted portfolio grants nothing
- a `status = 'DELETED'` portfolio grants nothing
- email matching is case-insensitive
- an unknown email grants nothing
- a blank or malformed email grants nothing
- refdata down with a cold cache denies
- refdata down with a warm cache serves the cached answer
- serving a stale answer does not renew its timestamp
- past the staleness ceiling, it denies
- an all-empty `usernames` result refuses to load

New to this app:

- an amend cannot move a deal **into** scope
- an amend cannot move a deal **out of** scope
- an undeclared route defaults to admin-only
- an admin is unaffected by a cold or stale map
- `blotter.csv` and `loan/export` are scoped
- a scoped user with zero portfolios gets an empty read and a 403 write

For Component 7, in `slack-trade-bot`:

- a booking into a portfolio the Slack user does not own is refused
- an inter-PTF booking where the user owns only one of the two legs is refused
  outright, not half-booked
- a Slack user with no readable email is refused rather than booked unscoped
- refdata unavailable refuses the booking with the same message the query path
  already uses

## Notes for implementation

- Python style in this repo: no one-liner `def`s, no aligned `=`, single space
  after commas.
- `docker/Dockerfile` does `COPY ./scripts ./scripts`, so a new module ships
  without touching a file list.
- Version bump via `update_version.py` plus a `chore:` commit on every main push.

## Open items

- **Which working copy is the deploy source?** `trade-booking` is git-ahead
  (Lighter snapshots, Binance gateway, v0.0.104); `middle-office-tools` sits
  back at the Binance-LTV commits. The `src/` JSX is currently identical between
  them but `server.js` is not, and most of this change lands in `server.js`.
- **Confirm danny.pang is `role = 'admin'`** in the TMS Postgres `users` table
  before deploying. Not yet verified - it needs a prod read.
