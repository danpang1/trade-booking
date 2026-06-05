# Mobile-Friendly Loan/Deal Enquiry — Design

**Date:** 2026-06-05
**Scope:** Make the Loan Enquiry **Binance VIP LTV card + collateral simulator** usable on a phone (priority), then the Deal/Loan Enquiry blotters, plus the app shell needed to reach them. Target: phone portrait (~375–430px).

## Goal

The Trade Management System is desktop-only: a hard-coded 208px sidebar, fixed-column grids, and wide tables. The user's top need is to **monitor Binance VIP loan LTV and collateral on a phone**, and ideally **work the what-if collateral simulator on a phone**. This change delivers that first, then makes the rest of the enquiry surfaces responsive — all without changing the desktop layout.

## Constraints & decisions

- **Target:** phone portrait only (~375–430px). Tablets keep the desktop layout. Single breakpoint at **≤640px** = "mobile".
- **Mechanism:** a `useIsMobile()` JS hook, not CSS/Tailwind breakpoints — the codebase drives layout through inline styles with pixel values that Tailwind `md:` classes cannot cleanly override.
- **VIP collateral lists** (live panel + simulator): render as **stacked cards per asset** on mobile (a handful of assets), not squished/scrolling tables.
- **Simulator** opens as a **full-screen sheet** on mobile so there's room to edit the scenario.
- **Deal/Loan blotter tables:** horizontal scroll with the **Deal Ref / loan ref** column pinned sticky-left; bulk-select checkbox column hidden on mobile (read/browse posture).
- **Both copies:** every code edit lands in **`middle-office-tools/src/TradeBookingForm.jsx`** AND **`trade-booking/src/TradeBookingForm.jsx`** (identical, 13,888 lines today).
- **No desktop regressions:** all mobile behavior is gated behind `isMobile` (or an opt-in prop); the desktop branch keeps its current markup/styles.

## Phasing

**Phase 1 — VIP card first (the priority deliverable).** Includes the unavoidable shell prerequisite so the card is actually viewable full-width on a phone:
1. `useIsMobile()` hook.
2. App shell → drawer (hamburger + slide-in sidebar), so Loan Enquiry is reachable and `<main>` spans full width on mobile.
3. VIP LTV live monitoring panel → mobile layout (header wrap, reflowed metric grids, collateral as stacked cards).
4. VIP collateral simulator → full-screen sheet on mobile, reflowed headline/triggers, editable collateral as stacked cards with the Adjust input front-and-centre.

**Phase 2 — the rest of the enquiry surfaces.**
5. Deal/Loan blotter tables → horizontal scroll + pinned ref column + hidden checkbox column.
6. Filter cards → single column.
7. KPI tile strips → 2-up.
8. Pagination bar → wrap + bigger tap targets.

## Out of scope

- Tablet-specific breakpoints.
- Create Deal / Amend / bulk-amend / CSV-export mobile optimization.
- Dashboard, Approvals, Users, API Tokens views.
- Making *all* modals full-screen on mobile — the full-screen sheet is opt-in (simulator only) to avoid regressing the booking-form / history / loan-schedule modals.
- Any backend / data / LTV-maths changes. `simulateVipBasket` and the polling logic are untouched; only presentation changes.

---

## Components

### 1. `useIsMobile()` hook
`window.matchMedia("(max-width: 640px)")`; returns a boolean, subscribes to `change`, cleans up on unmount; defensively returns `false` if `matchMedia` is unavailable. Placed near `useClock`. Single source of truth.

**Interface:** `const isMobile = useIsMobile();` · **Depends on:** `window.matchMedia`.

### 2. App shell → drawer (`TradeBookingForm` shell, ~11882–12166)
- New `navOpen` state (default `false`).
- **Hamburger button** in the header, left of the logo, rendered only when `isMobile`; toggles `navOpen`.
- **Sidebar `<aside>`:** on mobile becomes `position: fixed; inset: 0 auto 0 0; z-index` above content, `translateX(-100%)` when closed / `0` when open, with a slide transition. A dimmed **backdrop** renders behind the open drawer; tapping it, or any nav item, closes the drawer (wrap the existing nav `onClick`s). Desktop: unchanged static 208px aside, no transform, no backdrop.
- **Header:** `px-6`→`px-4` on mobile; hide the "Trade Management System" subtitle on mobile so hamburger + logo + clock + status dots fit. On mobile the aside is out of flow (fixed) so `<main>` spans full width.

**Acceptance:** At 390px the main panel is full-width; hamburger slides the nav in over a backdrop; tapping a nav item navigates and closes. Desktop sidebar identical to today; no hamburger.

### 3. VIP LTV live monitoring panel (`LoanEnquiry`, ~8691–8972)
The accent card stays; its internals reflow on mobile:
- **Header strip** (title · "current LTV X% · as of …" · *Simulate* · *↻* · *Copy*): add `flex-wrap`; on mobile the action buttons (Simulate / refresh / Copy) wrap to a second row under the title + LTV. Keep all actions — Simulate and Copy are wanted on mobile.
- **Headline metrics** (`repeat(3,1fr)`: Loan / Collateral / Borrowable USDT): on mobile reflow so values don't clip — single column stack (each metric full-width row) using `isMobile ? "1fr" : "repeat(3, minmax(0,1fr))"`. Cell borders switch from right-borders to bottom-borders on mobile.
- **Buffer summary** (`repeat(2,1fr)`: margin call / liquidation): keep 2 columns on mobile (short pp values pair naturally); reduce padding if tight.
- **Collateral basket** (currently a 6-col `<table>`, NOT wrapped, inside an `overflow:hidden` card): on mobile replace the table with a **stacked list of asset cards**. Each card:
  - Top row: asset symbol (+ "stable" tag) and its USD value.
  - Body: small label/value grid — Qty, Current px, MC px, Liq px.
  - The Qty stays tappable → `openVipSim(asset)` (preserves the existing "tap a qty to simulate that asset" behavior); the whole card may carry a "Simulate" affordance.
  - A final **Total collateral** summary row/card.
  - Desktop keeps the existing table unchanged.
- The `overflow:hidden` on the card is fine once the inner table is replaced by cards (no horizontal overflow on mobile).

**Acceptance:** On a 390px phone the panel reads cleanly top-to-bottom: status accent, current LTV + actions, loan/collateral/borrowable, buffers, then one card per collateral asset with qty/value/trigger prices and a total — no clipping, no sideways scroll. Tapping an asset card / qty opens the simulator focused on that asset.

### 4. VIP collateral simulator (`VipCollateralSimulatorModal` ~7674; `ModalShell` ~2748)
- **Full-screen sheet on mobile:** add an opt-in `mobileFullScreen` prop to `ModalShell`. When `isMobile && mobileFullScreen`, the wrapper uses `top:0; padding:0` and the panel becomes `width:100vw; height:100vh; max-* none; border:none` (slide-up or fade). The simulator passes `mobileFullScreen`. Other modals are unaffected (prop defaults off). Close button stays reachable (top-right, within safe tap area).
- **Header** (title · baseline · Reset · Copy): `flex-wrap`; actions wrap under the title on mobile. Keep Reset + Copy.
- **Headline readouts** (`repeat(4,1fr)`: Loan input / Sim LTV / Buffer MC / Buffer Liq): on mobile → **2 columns** (`repeat(2, minmax(0,1fr))`). The Loan-amount cell (with the `adjust ±` input) stays a first-class cell.
- **Editable collateral basket** (currently a 9-col table with the only qty input being "Adjust (+/−)"): on mobile replace with **stacked editable cards**, one per `simRows[i]`:
  - Header: asset (or the SYMBOL `<input>` for added rows) + remove ✕.
  - Primary control: the **Adjust (+/−) `<input>`**, prominent and full-width-ish (the main thing the user edits on mobile).
  - Read-outs: Current qty, New qty, Price (input only for added rows), Value, MC px, Liq px — as a compact label/value grid.
  - Focused-asset highlight (the `focusAsset` left-border / bg) carries over to the card.
  - Below the list: the **"+ Add asset"** button and the **Total collateral** line.
  - Desktop keeps the existing editable table unchanged.
- **Trigger detail** (`repeat(2,1fr)`): → 1 column on mobile. Disclaimer unchanged (already wraps).
- The loan-amount input, all number formatting (`vipGroupNum`, `onNum`), `simulateVipBasket`, Reset/Copy logic are reused as-is — only the layout container changes.

**Acceptance:** On a 390px phone, tapping Simulate opens a full-screen sheet; headline shows 2-up (Loan input + Sim LTV on top); each collateral asset is a card with a clearly tappable Adjust input; editing Adjust updates New qty / Value / Sim LTV / buffers live; Add asset and Reset/Copy work; ✕ closes. Desktop simulator is byte-for-byte unchanged.

### 5. Deal/Loan blotter tables (Phase 2 — Deal ~6584; Loan ~9675)
Real `<table>`s already wrapped in `overflow-x-auto`.
- Add `WebkitOverflowScrolling: "touch"` to the scroll wrapper.
- **Hide the bulk-select checkbox column** (`<th>` + each `<td>`) on mobile.
- **Sticky Deal Ref / loan ref column:** the ref `<th>`/`<td>` get `position: sticky; left: 0; z-index` and an explicit background matching the row's alternating bg / header bg (the sticky cell needs its own opaque bg because row bg is set via JS hover handlers). History icon column stays, not pinned. Hover bg effect on the sticky cell is acceptable to drop on touch.

**Acceptance:** mobile blotters scroll horizontally with momentum; ref column pinned left; checkbox column gone. Desktop unchanged.

### 6. Filter cards (Phase 2 — Deal ~6420; Loan equivalent)
- `gridTemplateColumns: "1fr 1fr"` filter grids → `"1fr"` on mobile; collapsible date-range sub-grid likewise stacks. Chip rows already `flex-wrap`. Verify the filter header strip wraps.

### 7. KPI tile strips (Phase 2 — Deal ~7449; Loan ~8463; shared exposure panel ~7128)
- Fixed `1fr 1fr 1fr` / `repeat(4, …)` grids → `repeat(2, minmax(0,1fr))` on mobile.

### 8. Pagination bar (Phase 2 — `EnquiryPaginationBar`, 5215)
- Already `flex-wrap`; confirm it stacks; bump Prev/Next + page-size tap-target padding on mobile.

## Data flow

No data flow changes. `isMobile` is derived from viewport width and only switches presentational styles / conditional rendering. All fetch / filter / pagination / LTV-simulation logic is untouched.

## Error handling

No new error paths. `useIsMobile` guards `window.matchMedia` existence (returns `false` if unavailable). Existing VIP loading/error states (`vipDetailLoading`, `vipDetailError`, `detail_error`) render the same on mobile.

## Testing / verification

- **Manual (primary):** run the app (`middle-office-tools` serves localhost:5180), DevTools device emulation at 390px:
  - **Phase 1:** open the drawer → Loan Enquiry → VIP card reads cleanly, collateral as cards; tap Simulate → full-screen sheet; edit an Adjust input and watch Sim LTV / buffers update; Add asset, Reset, Copy, ✕.
  - **Phase 2:** Deal & Loan blotters scroll with ref pinned + checkbox hidden; filters stack; KPIs 2-up; pagination wraps.
  - Resize to ≥1024px: layout identical to current `main`.
- **Existing tests:** `loanSearch.test.mjs` (pure logic) — run to confirm no import breakage.
- No new automated UI tests (component has none; manual device-emulation check is the bar).

## Rollout notes

- Apply identical edits to both `TradeBookingForm.jsx` copies.
- `trade-booking` ships via CI and needs a manual `python scripts/update_version.py` + chore commit before going live (project convention) — a release step when ready to ship, not part of implementation.
- Phase 1 can ship independently of Phase 2.
