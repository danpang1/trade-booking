# Handoff: Trade Booking UI Redesign

A layout-only redesign of the Tokka Labs Trade Management System: tighter blotter, drawer-based booking form, redesigned Pending Bookings queue, and a surfaced audit trail. No new pages, no new features.

---

## About the Design Files

The files in `references/` are **design references created in HTML/JSX** — prototypes that show intended look and behavior. They are not production code to copy directly.

The task is to **recreate these designs in the Tokka Labs codebase's existing environment** (whichever framework, component library, and state management the app is built in) using its established patterns. The tokens (`tokens.css` / `tokens.json`) should plug into whatever token system the codebase already has — replace existing values rather than introducing a parallel token set.

If no environment exists yet, choose React + TypeScript and a headless component approach (Radix / Headless UI primitives) so the visual layer can be implemented cleanly against the tokens here.

---

## Fidelity

**High-fidelity.** Colours, type sizes, row heights, and spacing values in `STYLE_GUIDE.md` are exact targets. Match them. The HTML in `references/` may be inspected pixel-by-pixel.

---

## Files

```
design_handoff_trade_booking/
├── README.md            ← you are here
├── PROMPT.md            ← ready-to-paste prompt for Claude Code
├── STYLE_GUIDE.md       ← visual rules, components, accessibility
├── tokens.css           ← CSS variables + utility classes
├── tokens.json          ← JSON form of the same tokens
└── references/          ← HTML prototypes — open in any browser
    ├── Trade Booking UI Review.html   (entry — pan/zoom canvas)
    ├── design-canvas.jsx              (canvas wrapper, ignore)
    ├── tokens.jsx                     (design-time tokens, see tokens.css instead)
    ├── parts.jsx                      (shared atoms: Pill, KV, Stat, …)
    ├── section-critique.jsx           (critique panels)
    ├── section-blotter.jsx            (PROPOSED BLOTTER — main reference)
    ├── section-booking.jsx            (PROPOSED BOOKING DRAWER — main reference)
    ├── section-workflow.jsx           (PENDING BOOKINGS + AUDIT TRAIL)
    ├── section-system.jsx             (design-system shelf — visual spec)
    └── app.jsx                        (canvas wiring)
```

To view the prototypes, open `references/Trade Booking UI Review.html` in a browser. Use the canvas to pan/zoom between sections.

---

## Screens / Views

### 1 · Deal Enquiry (the blotter)

**Purpose:** the operator's primary view of all bookings. Filter, sort, select, and act on deals.

**Reference:** `references/section-blotter.jsx` (`ProposedBlotter` component)

**Layout, top to bottom:**
1. Top chrome bar — `--panel` background, `44px` height. Brand mark · `⌘K` search · status dots + UTC clock · user avatar. *Preserved from current design.*
2. Left sidebar — `192px` wide, `--paper` background, `1px solid --rule` right border. `+ NEW DEAL` primary button at top, then grouped nav links (Books / Reports / Admin) with active state showing a 2px ink left-border and `--paper-2` background.
3. Page header — `Deal Enquiry` in Source Serif 26px, with secondary line in mono 11px ink-3 (`487 deals · 18 visible · last sync …`). Right-side actions: `+ Date Filter`, `Save View`, `↓ CSV`, `↓ Trade Bookings`, `+ New Deal`.
4. Saved-views tabs — horizontal scroll of named filter presets. Active tab has 2px ink underline, count badge in `--ink` background. Inactive tabs use `--paper-2` count badge.
5. KPI strip — five tiles in a row, each with 3px coloured left border. See STYLE_GUIDE §6.7. Trailing sparkline on the right.
6. Filter chip rows — two rows of chip groups, separated by 1px vertical rules. Group labels in `.tk-label` style. Active chips use ink-on-paper inversion. Each chip shows a count.
7. Table — sticky header row `8px` padding, `--paper-2` background, mono 10px uppercase column titles. Body rows `28px` minimum height. Alternating rows get `rgba(0,0,0,0.015)` background.
8. Footer aggregations — full-width strip with `2px solid --ink` top border, `--paper-2` background. Contains: selection count, sum of amounts, sum of notional (tabular-nums), status histogram pills, bulk-action buttons, keyboard legend.

**Column layout (grid-template-columns):**
```
34px  92px   132px  80px  56px  84px  200px  168px  60px  96px        88px   144px  102px         92px  28px
☐     Updated Ref    Type  Dir   Ptf   Name   CP     Asset Amount→    Venue  Tag    Notional→     Status ⋯
```

Right-align numeric columns (`Amount`, `Notional`). Reference links inside a cell get a sub-row showing the linked deal (`↳ MCF00000037`) at 10px ink-3.

**Direction glyph** in the `Dir` column: `▲ LONG` (buy colour), `▼ SHORT` (sell colour), `⇄ FUNDS` (ink-2). Small triangle + uppercase mono label.

**Selected row:** `--paper-3` background + `inset 3px 0 0 --ink` box-shadow on the left.

**Hover row:** background → `--paper-2`. Reveal a `⋯` kebab in the last column (default `opacity: 0.5`).

### 2 · Create Deal → right-side drawer

**Purpose:** book a new trade without losing the blotter context.

**Reference:** `references/section-booking.jsx` (`ProposedBookingDrawer` component)

**Key change from today:** the current `Create Deal` is a full-screen modal. Replace with a **right-side drawer** taking 60% of viewport width (~`1180px` on a `1920` viewport). The blotter remains visible underneath at ~55% opacity, behind a `rgba(13,12,10,0.18)` scrim.

**Drawer header:**
- Left: small mono caption (`NEW DEAL · DRAFT MFX-…`) above a Source Serif 22px title (`Book a Spot Trade`).
- Right: segmented tab control (`Spot | Futures | Cashflow | Loan | Other`). Active tab uses `--ink` background, `--paper` text. Then `↗ Open full` and `✕` close buttons.

**Drawer body — two columns:**
- Left column (~`760px`, scrollable): the form, broken into three sections with `◆ Section Name` headers:
  - `◆ Trade Summary` (step 1 of 3) — internal/external IDs, dates, portfolio, entity, counterparty
  - `◆ Trade Details` (step 2 of 3) — direction toggle, base/quote pair card, price, fees, account
  - `◆ Comments & Attachments` (step 3 of 3) — notes + drag-drop upload zone
- Right column (`380px`, `--paper` background, `1px solid --rule` left border): draft summary card on top, then **Live Record (JSON)** filling the rest. The JSON pane uses `--panel` background, `--panel-ink` text, mono 11px, line-height 1.6.

**Direction toggle:** segmented control of two buttons. Active state uses `--signal-buy` or `--signal-sell` as background with `--paper` text.

**Pair card:** the base/quote inputs sit in a `--paper-2` background block with `14px` padding. Grid: `1fr 1.4fr 12px 1fr 1.4fr` with the `×` glyph centred in column 3.

**Drawer footer:** `2px solid --ink` top border, `--paper-2` background, `12px 24px` padding. Contents: error count + dot, mod-time + attachment count, `Reset` / `Save Draft (⌘S)` / `Generate Output (⌘↵)` buttons.

**Validation:** errors render inline directly under the field as mono 10.5px in `--signal-sell`, prefixed with a 12×12 round badge containing `!`. The footer shows a rolled-up count. Do NOT show a long list of errors at the bottom of the form — that was the previous pattern.

### 3 · Pending Bookings

**Purpose:** maker submits → checker approves/rejects. Replaces the sparse current panel.

**Reference:** `references/section-workflow.jsx` (`ApprovalQueue` component)

**Layout:**
- Header — Source Serif 22px `Pending Bookings` + tab control on the right (`PENDING 2 | APPROVED 11 | REJECTED 1`). Same segmented control style as the drawer's deal-type tabs.
- Body section 1 — `Awaiting action · N`. Each pending booking is a card with `--paper-2` background, `1px solid --rule-2` border, `3px --status-confirmed` left border. Inside: ref link + type pill + direction pill on one row, submitted-time + maker on the right. Then a single-line summary in mono 13px. Then the action button row: `✓ Approve (A)` primary, `✕ Reject (R)` danger, `↗ Open draft` secondary.
- Body section 2 — `Recently decided` list. 1px rule between rows, alternating background, mono 11px throughout. Columns: ref · decision pill · type · time · `by <user> · "note"`.

### 4 · Audit trail peek

**Purpose:** surface the history already implied by the clock icon in the current blotter's first column.

**Reference:** `references/section-workflow.jsx` (`AuditHistory` component)

**Layout:** a side-peek panel ~`580px` wide. Vertical timeline with a 1px `--rule-2` spine and 12×12 circular event markers (each in its event-type colour with a 2px paper ring). Each event shows time (mono 11px tabular-num), event-type pill, actor name, and details:
- `EDIT` events render a **diff badge pair**: old value with `text-decoration: line-through` on a `--signal-sell-bg` chip, arrow, new value on a `--signal-buy-bg` chip.
- `STATUS` events render the two state pills with an arrow between.
- `CREATE`, `APPROVE`, `ATTACH` events render a single grey detail line beneath.

Footer block: `--paper-2` background, 3px confirmed left border, with a "Compliance export — generate signed PDF" affordance.

---

## Interactions & Behavior

- **`⌘K`** opens command palette (search deals/counterparties/refs)
- **`B`** opens the new-deal drawer
- **`A`** approves the currently focused pending booking (on Pending Bookings screen)
- **`R`** rejects the currently focused pending booking
- **`/`** focuses the search input
- **`J` / `K`** moves focus down/up a row in the blotter
- **`⌘S`** saves the booking drawer as draft
- **`⌘↵`** submits the booking drawer

**Transitions:** all hover state changes use `0.12s` ease. Drawer slide-in: `0.18s cubic-bezier(0.2, 0.7, 0.3, 1)`. No spring physics; this is a back-office app.

**Persistence:** saved-views tabs persist user filter selections. The drawer remembers field values until explicitly Reset or Submitted.

---

## State Management

- **Filter state** — chips, saved-view tab, search input. Persist to user preferences.
- **Selection state** — set of selected booking IDs (for bulk actions in footer).
- **Drawer state** — open/closed, deal-type, form values, validation errors, attachment list.
- **Pending Bookings state** — list of items in `pending`, `approved`, `rejected` tabs; refresh on submit/decision.
- **Audit drawer state** — currently inspected booking ID; event list lazy-loaded.

---

## Design Tokens

See `tokens.css` and `tokens.json` for the full set. Highlights:

- **Paper:** `#ffffff`, `#f6f5f2`, `#ecebe7`
- **Ink:** `#161513`, `#46423b`, `#6e695f`, `#a09a90`
- **Rules:** `#e6e3dd`, `#c9c5bd`
- **Status:** pending `#a37312`, confirmed `#3a5fb0`, processed `#2a7560`, settled `#1f6f4a`, cancelled `#7a7363`
- **Signal:** buy `#1f6f4a`, sell `#a83838`, warn `#a35c12`, link `#365dbb`
- **Row heights:** 28 / 36 / 52
- **Radius:** 2 / 3 / 4 (never higher)
- **Spacing:** 4 / 8 / 12 / 16 / 20 / 24 / 32

---

## Out of Scope

The review touched on these but the user **explicitly declined** them for this round:

- ❌ Pre-trade risk checks (counterparty exposure, sanctions, concentration, settlement-window)
- ❌ Live position / exposure panel
- ❌ New routes or pages
- ❌ Brand changes; the top chrome stays as-is

If you find yourself adding any of the above, stop and flag with the user first.

---

## Assets

- **Fonts** — Source Serif 4 and JetBrains Mono. Both are open-source via Google Fonts. The prototype imports them; in production, self-host or use the codebase's existing font pipeline.
- **Icons** — no icon library bundled. The prototype uses Unicode glyphs (`◆`, `▲`, `▼`, `⇄`, `⋯`, `↳`, `✓`, `✕`, `⚠`). In production, swap for the codebase's existing icon set (Lucide / Phosphor / etc.) at matching sizes.
- **Logos** — the `T` glyph in the top-left brand mark is a placeholder typesetting of the brand letter; use the real Tokka Labs mark.
