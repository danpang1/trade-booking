# Tokka Labs · TMS — Visual Style Guide

Reference document for implementing the redesigned trade-booking UI in production code.

This is a **high-fidelity** design guide. Treat colours, spacings, and type values as exact targets.

---

## 1 · Philosophy

> Paper + ink + signal. Mono for positional data, serif for identity. Square corners, hairline borders, dense rows. **Saturation is reserved for status and direction** — never used for chrome or decoration.

The aesthetic reads like a printed trade ticket — deliberate, dense, unbranded in the marketing sense. Resist any urge to add a brand accent for visual interest; it dilutes the signal value of the status palette.

---

## 2 · Typography

Two families. Never mix them in the same span.

| Family | Use for | Sizes |
|---|---|---|
| **Source Serif 4** (weights 400/500/600/700) | Page titles, drawer/panel titles, section headers (`◆ Section Name`) | 15, 22, 26 |
| **JetBrains Mono** (weights 400/500/600) | Everything else — table cells, refs, codes, numbers, buttons, labels, inputs, status pills | 10, 11, 12, 13 |

**Letter spacing:**
- Serif headings: `-0.01em` (tight)
- Uppercase labels: `+0.06em` (label)
- Mono body: `0em` (flat)

**Tabular numbers:** apply `font-variant-numeric: tabular-nums` to every column of numbers in tables and KPI tiles. Misaligned digits in a blotter are the #1 readability tell of a poorly built financial UI.

**Type rules:**
1. Page title (`Deal Enquiry`, `Pending Bookings`) → **Source Serif, 26px, semibold, -0.01em**.
2. Drawer / panel title (`Book a Spot Trade`, `Approval`) → **Source Serif, 22px, semibold**.
3. Section header inside a form/card (`◆ Trade Summary`, `◆ Live Record`) → **Source Serif, 15px, semibold**, prefixed with the `◆` glyph.
4. Labels (`PORTFOLIO`, `BASE ASSET`) → **Mono, 10px, uppercase, +0.06em, color: ink-3**.
5. Data (refs, prices, amounts) → **Mono, 12px, weight 500**.

---

## 3 · Colour

### Surface — paper, panel inks

| Token | Hex | Use |
|---|---|---|
| `--paper`     | `#ffffff` | Primary background |
| `--paper-2`   | `#f6f5f2` | Row alt, sidebar, filter strip |
| `--paper-3`   | `#ecebe7` | Panel inset, selected row |
| `--panel`     | `#0d0c0a` | Top chrome, dark JSON inset |
| `--panel-ink` | `#ece8dc` | Text on panel |
| `--panel-ink-2` | `#8a8678` | Secondary text on panel |

### Ink — text and iconography

| Token | Hex | Use |
|---|---|---|
| `--ink`   | `#161513` | Primary text |
| `--ink-2` | `#46423b` | Secondary text |
| `--ink-3` | `#6e695f` | Tertiary, labels, hints |
| `--ink-4` | `#a09a90` | Disabled, placeholder |

### Hairlines

| Token | Hex | Use |
|---|---|---|
| `--rule`   | `#e6e3dd` | Light divider, row border |
| `--rule-2` | `#c9c5bd` | Input border, stronger hairline |
| `--ink` (as `2px solid`) | — | Footer-strip separator above totals |

### Status — applied to pills, dots, row borders

| Status | Foreground | Background |
|---|---|---|
| pending   | `#a37312` | `#f8ebcb` |
| confirmed | `#3a5fb0` | `#e2e9f6` |
| processed | `#2a7560` | `#dfeee7` |
| settled   | `#1f6f4a` | `#dff0e3` |
| cancelled | `#7a7363` | `#e6e2d6` |

### Signal — direction, validation

| Signal | Foreground | Background |
|---|---|---|
| buy / long / received / approved | `#1f6f4a` | `#dff0e3` |
| sell / short / paid / rejected | `#a83838` | `#f5dcd7` |
| warn | `#a35c12` | `#f8e5c8` |
| link | `#365dbb` | — |

**Colour rule:** the status colour stays the same wherever the status appears — pill, dot, row border-left, footer histogram bar. Never re-map.

---

## 4 · Geometry

### Radius
- Default: `3px` (`--radius-sm`)
- Pills, chips: `2px` (`--radius-xs`)
- Larger cards: `4px` (`--radius-md`)
- **Never above 4px.** Anything more rounded reads as consumer-app.

### Borders
- `1px solid var(--rule)` for table dividers, card hairlines
- `1px solid var(--rule-2)` for input borders, button borders
- `2px solid var(--ink)` for the footer-strip separator above totals

### Shadows
- **Avoid box-shadows** on cards and rows.
- Drawer chrome may use one shadow: `-20px 0 60px rgba(0,0,0,0.18)`.

### Spacing scale (4px base)
4 · 8 · 12 · 16 · 20 · 24 · 32

---

## 5 · Density

| Row type | Height | Use |
|---|---|---|
| Dense | `28px` | Default blotter row, queue rows |
| Comfortable | `36px` | Forms, settings |
| Card | `52px` | Cashflow ledger, attachment list |

Aim for ~38 dense rows per 1080px viewport on the blotter. The previous design fit ~14 — that's the single biggest readability win.

---

## 6 · Components

### 6.1 Status pill
- Height ~16–18px, padding `2px 6px`, radius `2px`
- 1px border same colour as foreground; background is the matching `bg` token
- All caps, mono 10px, letter-spacing 0.06em, weight 600
- Optional 6px circular dot on the left, same colour as foreground

### 6.2 Filter chip (chip-row above tables)
- Height 24px, padding `4px 10px`, radius `2px`
- Inactive: transparent bg, `--ink-2` text, `--rule-2` border
- Active: `--ink` bg, `--paper` text, `--ink` border
- Optional count badge to the right (`Pending 6`) — different colour by state

### 6.3 Button
- Default: mono 11px, padding `6px 10px`, radius `3px`, paper bg, `--rule-2` border
- Primary: `--panel` bg, `--panel-ink` text
- Danger: `--signal-sell` text and border, paper bg
- Hover: bg lightens to `--paper-2` (default) or `#232017` (primary)

### 6.4 Input
- Mono 12px, padding `6px 8px`, radius `3px`
- `--rule-2` border; on focus, border becomes `--ink-2` with `inset 0 0 0 1px --ink-2`
- Error state: `--signal-sell` border with `inset 0 0 0 1px --signal-sell`

### 6.5 Keyboard glyph (`<kbd>`)
- Mono 10px, padding `1px 5px`, 1px top/sides border, 2px bottom border (suggests key cap)
- `--rule-2` border, `--paper` bg, `--ink-2` text

### 6.6 Link (in-table refs like `MCF00000038`)
- `--signal-link` colour, 1px dotted underline. No solid underlines.
- Hovered: cursor pointer; consider revealing a peek tooltip with linked deal preview.

### 6.7 KPI tile
- Layout: 3px solid coloured left border, content padded `8px 12px`
- Label (mono 10px label-style), then big number (mono tabular-num 18px semibold), then sub (mono 10px ink-3)
- Border colour is the semantic colour for the metric (confirmed for notional, pending for queue counts, warn for due-today)

### 6.8 KV (key + value pair)
- Stack: label on top (`.tk-label`), value below (mono 13px weight 500). 2px gap.

### 6.9 Pill / dot / row consistency
- A pending booking displays:
  - **Row**: optional 3px left border in `--status-pending`
  - **Pill**: `Pending` in the Status column
  - **Footer histogram**: same colour for the pending segment
- All three are the same hex.

---

## 7 · The Top Chrome (preserved)

Keep the dark chrome bar `--panel` background, height `44px`, full width. Contents left-to-right:
- Brand mark (`T` glyph + `Tokka Labs` serif + `TRADE MGMT` caption)
- Inline search field with `⌘K` kbd hint, slight semi-transparent bg
- System status dots (services up, ws feeds) + UTC clock
- User avatar (24×24 paper-on-panel)

---

## 8 · Patterns that didn't exist before — but use only existing data

The brief was *layout-only updates to existing screens*. Three patterns are new but they consume only data the system already has:

1. **Saved-views tabs above the blotter** — replays a saved filter set. No new schema; just persistence of the filter row.
2. **KPI strip across the top of the blotter** — `notional open`, `pending count`, `oldest pending age`, etc — are all derivable from the booking table.
3. **Audit trail peek** — surfaces the history hinted at by the existing clock icon. Backend already records this; the UI just exposes it.

Pre-trade risk checks, live position panels, counterparty limit gauges — explicitly **out of scope** for this round.

---

## 9 · Accessibility

- Status is never communicated by colour alone — every pill has a text label and most have a dot or glyph.
- Maintain 4.5:1 contrast for all text against its background. Default ink on paper is 18:1; ink-3 on paper is ~5.7:1 (passes AA).
- Every interactive element needs a visible focus ring — use the same inset `--ink-2` ring as input focus.
- All hotkeys (`⌘K`, `B`, `A`, `R`, `/`, `J`, `K`) must work without the mouse and be announced in the keyboard legend at the blotter footer.
