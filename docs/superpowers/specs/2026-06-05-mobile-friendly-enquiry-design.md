# Mobile-Friendly Deal & Loan Enquiry — Design

**Date:** 2026-06-05
**Scope:** Make the Deal Enquiry and Loan Enquiry views (plus the app shell needed to reach them) usable on a phone in portrait orientation (~375–430px).

## Goal

Today the Trade Management System is desktop-only: a hard-coded 208px sidebar, fixed-column KPI grids, and wide data tables. On a phone the sidebar covers half the screen and the views are unusable. This change makes navigation and the two enquiry views work on a phone, while leaving the desktop layout byte-for-byte unchanged.

## Constraints & decisions

- **Target:** phone portrait only (~375–430px). Tablets keep the desktop layout. Single breakpoint at **≤640px** = "mobile".
- **Tables:** keep them as tables with **horizontal scroll** (not a card rewrite). Pin the **Deal Ref / loan ref** column sticky-left.
- **Posture:** read/browse focused. Bulk-amend, Create Deal, and CSV-export polish are out of scope; the bulk-select checkbox column is hidden on mobile.
- **Shell:** include the responsive sidebar drawer (hamburger + slide-in) so the views are reachable.
- **Mechanism:** a `useIsMobile()` JS hook, not CSS/Tailwind breakpoints — the codebase drives layout through inline styles with pixel values, which Tailwind `md:` classes cannot cleanly override.
- **Both copies:** every code edit must land in **`middle-office-tools/src/TradeBookingForm.jsx`** AND **`trade-booking/src/TradeBookingForm.jsx`** (identical, 13,888 lines today).
- **No desktop regressions:** all mobile behavior is gated behind `isMobile`; the desktop branch keeps its current markup/styles.

## Out of scope

- Tablet-specific breakpoints.
- Create Deal / Amend / bulk-amend / CSV-export mobile optimization.
- The Dashboard view, Approvals inbox, Users, API Tokens views.
- Any backend / data changes.

## Components

### 1. `useIsMobile()` hook
A small hook using `window.matchMedia("(max-width: 640px)")`. Returns a boolean, subscribes to `change`, cleans up on unmount. Placed near `useClock`. Single source of truth for the breakpoint. SSR-safe guard not required (client-only app), but it reads `window` lazily.

**Interface:** `const isMobile = useIsMobile();`
**Depends on:** `window.matchMedia`.

### 2. App shell → drawer (`TradeBookingForm` shell, ~11882–12166)
- New `navOpen` state (default `false`).
- **Hamburger button** in the header, left of the logo, rendered only when `isMobile`. Toggles `navOpen`.
- **Sidebar `<aside>`:** on mobile becomes `position: fixed; top: 0; bottom: 0; left: 0; z-index` above content, transformed `translateX(-100%)` when closed / `0` when open, with a transition. A dimmed **backdrop** (`position: fixed`, semi-transparent) renders behind the open drawer; tapping it closes. Tapping any nav item closes the drawer (wrap the existing `onClick`s). Desktop: unchanged static 208px aside (no transform, no backdrop).
- **Header:** `px-6`→`px-4` on mobile; hide the "Trade Management System" subtitle on mobile so hamburger + logo + clock + status dots fit on one row. Clock/date stays.
- Body wrapper stays `flex flex-1 min-h-0`; on mobile the aside is taken out of flow (fixed) so `<main>` spans full width.

**Acceptance:** On a 390px viewport, the main panel uses the full width; tapping the hamburger slides the nav in over a backdrop; tapping a nav item navigates and closes the drawer. On desktop the sidebar is identical to today and no hamburger shows.

### 3. Filter cards (Deal Enquiry ~6420; Loan Enquiry equivalent)
- The `gridTemplateColumns: "1fr 1fr"` filter grids become `"1fr"` (single column) on mobile.
- The collapsible date-range sub-grid (~6541 and Loan equivalent) likewise stacks to one column on mobile.
- Status/portfolio chip rows already `flex-wrap` — no change needed.
- The filter header strip (Filters / +Portfolio / +Date / Clear / CSV) already uses flex with gaps; verify it wraps on narrow widths, add `flex-wrap` if it overflows.

**Acceptance:** filter inputs stack vertically and are full-width / tappable on mobile; unchanged 2-column layout on desktop.

### 4. KPI tile strips (Deal ~7449; Loan ~8463; shared exposure panel ~7128)
- Fixed `1fr 1fr 1fr` / `repeat(4, minmax(0,1fr))` grids drop to **2 columns** on mobile (`repeat(2, minmax(0,1fr))`).
- Tile internal text already small; keep as-is. Ensure tiles remain tappable (the expandable ones).

**Acceptance:** KPI tiles render in a readable 2-up grid on mobile, full multi-column on desktop.

### 5. Enquiry tables (Deal ~6584; Loan ~9675)
The tables are real `<table>`s already wrapped in `overflow-x-auto`.
- Add `style={{ WebkitOverflowScrolling: "touch" }}` to the scroll wrapper for smooth momentum scrolling on iOS.
- **Hide the bulk-select checkbox column** (`<th>` + each row's `<td>`) on mobile — gate its render behind `!isMobile`.
- **Sticky Deal Ref / loan ref column:** the ref `<th>` and `<td>` get `position: sticky; left: 0; z-index` and an explicit background (matching the row's alternating bg / header bg) so scrolling cells slide under it. With the checkbox column hidden on mobile, the ref column is the natural left anchor. The History icon column stays but is not pinned.
  - Implementation note: the row background is set via JS hover handlers (`onMouseEnter/Leave` swap `e.currentTarget.style.background`). The sticky cell needs its own opaque bg independent of the `<tr>` bg, so the sticky `<td>` carries an explicit `background` matching `altBg`. Hover effect on the sticky cell is acceptable to drop on mobile (no hover on touch).
- Reduce horizontal cell padding on mobile if needed for density (optional; only if tables feel cramped).

**Acceptance:** on mobile the table scrolls horizontally with momentum; the Deal Ref / loan ref column stays pinned at the left edge while other columns scroll under it; the checkbox column is gone. Desktop table is unchanged (checkbox visible, no sticky needed but harmless).

### 6. Pagination bar (`EnquiryPaginationBar`, 5215)
- Already `flex items-center justify-between flex-wrap gap-2` — confirm it wraps to two rows on narrow widths.
- Increase Prev/Next and page-size tap targets on mobile (padding bump) for thumb use.

**Acceptance:** pagination controls remain reachable and tappable on mobile without horizontal overflow.

## Data flow

No data flow changes. `isMobile` is derived state from viewport width; it only switches presentational styles and conditional rendering. All fetch/filter/pagination logic is untouched.

## Error handling

No new error paths. `useIsMobile` guards `window.matchMedia` existence defensively (returns `false` if unavailable).

## Testing / verification

- **Manual (primary):** run the app (`middle-office-tools` serves localhost:5180), open DevTools device emulation at 390px:
  - Sidebar drawer opens/closes via hamburger + backdrop + nav-item tap.
  - Deal Enquiry & Loan Enquiry: filters stack, KPIs 2-up, table scrolls horizontally with Deal Ref pinned, checkbox column hidden, pagination wraps.
  - Resize to desktop (≥1024px): layout identical to current `main`.
- **Existing tests:** `loanSearch.test.mjs` is pure logic — unaffected; run to confirm no import breakage.
- No new automated UI tests (the project has none for this component; manual device-emulation check is the verification bar).

## Rollout notes

- Apply identical edits to both `TradeBookingForm.jsx` copies.
- `trade-booking` ships via CI and needs a manual `python scripts/update_version.py` + chore commit before the change goes live (per project convention). The version bump is a release step, performed when the user is ready to ship — not part of the implementation itself.
