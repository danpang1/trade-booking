# Mobile-Friendly VIP LTV Card — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Loan Enquiry **Binance VIP LTV monitoring card** and its **what-if collateral simulator** usable on a phone (portrait), including the minimal app-shell drawer needed to reach the view full-width.

**Architecture:** Add a `useIsMobile()` hook (≤640px) as the single breakpoint source. Gate every mobile change behind `isMobile` (or an opt-in `mobileFullScreen` prop) so the desktop layout is untouched. On mobile: the 208px sidebar becomes a slide-in drawer; the VIP live panel reflows and renders collateral as stacked per-asset cards; the simulator opens as a full-screen sheet with collateral as editable cards (the Adjust input front-and-centre). No backend, no LTV-maths changes — presentation only.

**Tech Stack:** React 19, Vite, Tailwind v4 (utility classes) + heavy inline styles, lucide-react icons. No UI test harness exists.

---

## Conventions (apply to EVERY task)

The two app copies are **byte-identical today and must stay identical**. All edits are made in the `middle-office-tools` copy, then mirrored to `trade-booking`:

- **MO** = `C:/Users/peter/OneDrive/Desktop/Claude/middle-office-tools/src/TradeBookingForm.jsx`
- **TB** = `C:/Users/peter/OneDrive/Desktop/Claude/trade-booking/src/TradeBookingForm.jsx`

After editing MO, mirror with: `cp "C:/Users/peter/OneDrive/Desktop/Claude/middle-office-tools/src/TradeBookingForm.jsx" "C:/Users/peter/OneDrive/Desktop/Claude/trade-booking/src/TradeBookingForm.jsx"`

**Build/verify command** (run from MO repo): `cd "C:/Users/peter/OneDrive/Desktop/Claude/middle-office-tools" && npm run build` → must exit 0 (Vite build succeeds, no JSX/syntax errors).

**Manual check:** `npm run dev` in MO (localhost:5180), Chrome DevTools device emulation at **390px**.

**Commit in BOTH repos** on branch `mobile-friendly-enquiry` (TB branch already exists; MO branch created in Task 0). Commit message footer:
```
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
```

### Note on TDD / testing

This component has **no UI test harness** (only `loanSearch.test.mjs`, pure logic; no jsdom/matchMedia). These changes are presentational JSX. Per the spec, the verification bar is **`npm run build` (compiles) + manual device-emulation**, not unit tests. So each task's "Verify" is a successful build plus the stated manual observation. Do **not** scaffold a new test framework — that's out of scope.

---

## Task 0: Setup — MO branch + `useIsMobile()` hook + build baseline

**Goal:** Establish the MO feature branch, confirm a clean baseline build, and add the breakpoint hook used by every later task.

**Files:**
- Modify: MO `TradeBookingForm.jsx` (add hook after `useClock`, ~line 9986; consume in `TradeBookingForm`, ~line 10131)
- Mirror: TB `TradeBookingForm.jsx`

**Acceptance Criteria:**
- [ ] MO repo on branch `mobile-friendly-enquiry`.
- [ ] Baseline `npm run build` passes before edits.
- [ ] `useIsMobile()` added; `const isMobile = useIsMobile();` present in `TradeBookingForm`.
- [ ] Build passes after edit; MO and TB byte-identical.

**Verify:** `cd middle-office-tools && npm run build` → exit 0; `diff MO TB` → identical.

**Steps:**

- [ ] **Step 1: Branch + baseline build**

```bash
cd "C:/Users/peter/OneDrive/Desktop/Claude/middle-office-tools"
git checkout -b mobile-friendly-enquiry
npm run build   # baseline must pass before we touch anything
```

- [ ] **Step 2: Add the hook** — in MO, immediately AFTER the `useClock` function (which ends at the line `}` before `export default function TradeBookingForm() {`, ~line 9986), insert:

```jsx
// Reactive viewport-width breakpoint. Mobile = phone portrait (<=640px).
// matchMedia only re-renders when crossing the breakpoint (not on every
// resize pixel). Hoisted function decl so components defined earlier in
// the file (e.g. ModalShell) can call it.
function useIsMobile(maxWidth = 640) {
  const query = `(max-width: ${maxWidth}px)`;
  const [isMobile, setIsMobile] = useState(() => (
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia(query).matches
      : false
  ));
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mql = window.matchMedia(query);
    const onChange = (e) => setIsMobile(e.matches);
    setIsMobile(mql.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);
  return isMobile;
}
```

- [ ] **Step 3: Consume it** — in `TradeBookingForm`, find `const clock = useClock();` (~line 10131) and add directly below:

```jsx
  const isMobile = useIsMobile();
```

- [ ] **Step 4: Mirror + build**

```bash
cp "C:/Users/peter/OneDrive/Desktop/Claude/middle-office-tools/src/TradeBookingForm.jsx" "C:/Users/peter/OneDrive/Desktop/Claude/trade-booking/src/TradeBookingForm.jsx"
cd "C:/Users/peter/OneDrive/Desktop/Claude/middle-office-tools" && npm run build
```
Expected: build exit 0.

- [ ] **Step 5: Commit both repos**

```bash
cd "C:/Users/peter/OneDrive/Desktop/Claude/middle-office-tools" && git add src/TradeBookingForm.jsx && git commit -m "feat(mobile): add useIsMobile breakpoint hook

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
cd "C:/Users/peter/OneDrive/Desktop/Claude/trade-booking" && git add src/TradeBookingForm.jsx && git commit -m "feat(mobile): add useIsMobile breakpoint hook

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 1: App shell → responsive drawer

**Goal:** On mobile, collapse the 208px sidebar into a hamburger-triggered slide-in drawer with a backdrop, so `<main>` spans full width and the views are reachable. Desktop unchanged.

**Files:**
- Modify: MO `TradeBookingForm.jsx` — lucide import; `navOpen` state (~9990); header (~11893–11913); body/aside (~11994–12166)
- Mirror: TB

**Acceptance Criteria:**
- [ ] At 390px: sidebar hidden by default; hamburger in header opens it over a dimmed backdrop; tapping a nav item or the backdrop closes it; `<main>` is full-width.
- [ ] Desktop (≥1024px): sidebar identical to today; no hamburger; no backdrop.
- [ ] Build passes; MO/TB identical.

**Verify:** `npm run build` → exit 0; manual at 390px (drawer opens/closes) and at 1280px (unchanged).

**Steps:**

- [ ] **Step 1: Import the Menu icon** — find the `lucide-react` import (it already imports `History, RotateCcw, Copy, Check, X, AlertCircle`, etc.) and add `Menu` to the named imports.

- [ ] **Step 2: Add drawer state** — in `TradeBookingForm`, find `const [appView, setAppView] = useState("booking");` (~line 9990) and add below:

```jsx
  const [navOpen, setNavOpen] = useState(false);
```

- [ ] **Step 3: Header padding + hamburger + hide subtitle** — the header opens (~11893) as:

```jsx
      <header
        className="flex items-center justify-between px-6 py-3 mb-4"
        style={{
          background: "#0d0d0d",
        }}
      >
        {/* LEFT — logo + system name as one vertical lockup */}
        <div className="flex flex-col items-start gap-1.5">
```

Replace those lines with (adds responsive padding, wraps hamburger + logo in a flex row):

```jsx
      <header
        className="flex items-center justify-between py-3 mb-4"
        style={{
          background: "#0d0d0d",
          paddingLeft: isMobile ? 14 : 24,
          paddingRight: isMobile ? 14 : 24,
        }}
      >
        {/* LEFT — hamburger (mobile) + logo + system name lockup */}
        <div className="flex items-center gap-2">
          {isMobile && (
            <button
              type="button"
              onClick={() => setNavOpen(true)}
              aria-label="Open menu"
              style={{
                background: "transparent", border: "none", color: "#ece7dd",
                padding: 6, marginRight: 2, cursor: "pointer",
                display: "inline-flex", alignItems: "center",
              }}
            >
              <Menu size={22} strokeWidth={1.75} />
            </button>
          )}
          <div className="flex flex-col items-start gap-1.5">
```

This adds ONE extra wrapping `<div>`, so its matching `</div>` must be added. Find the end of the logo lockup — the subtitle span closes then `</div>` (~line 11913, the `</div>` right before the `{/* RIGHT … */}` comment). Change that single `</div>` into two:

```jsx
          </div>
        </div>
```

(The first `</div>` closes the existing logo lockup; the second closes the new `flex items-center gap-2` wrapper.)

- [ ] **Step 4: Hide subtitle on mobile** — the subtitle (~11907):

```jsx
          <span
            className="text-[9px] tracking-[0.34em] uppercase font-mono"
            style={{ color: "#9a9488", fontWeight: 400, paddingLeft: 1 }}
          >
            Trade Management System
          </span>
```

Wrap it so it only renders on desktop:

```jsx
          {!isMobile && (
          <span
            className="text-[9px] tracking-[0.34em] uppercase font-mono"
            style={{ color: "#9a9488", fontWeight: 400, paddingLeft: 1 }}
          >
            Trade Management System
          </span>
          )}
```

- [ ] **Step 5: Backdrop + off-canvas aside** — the body + sidebar open (~11993):

```jsx
      {/* ════ BODY — left sidebar + main panel ════ */}
      <div className="flex flex-1 min-h-0">
        {/* ─── SIDEBAR ─── */}
        <aside
          className="shrink-0 flex flex-col"
          style={{
            width: 208,
            borderRight: `1px solid ${BB.border}`,
            background: BB.bg,
          }}
        >
```

Replace with (adds backdrop before the aside, and makes the aside fixed/off-canvas on mobile):

```jsx
      {/* ════ BODY — left sidebar + main panel ════ */}
      <div className="flex flex-1 min-h-0">
        {/* Mobile drawer backdrop — taps close the nav. */}
        {isMobile && navOpen && (
          <div
            aria-hidden
            onClick={() => setNavOpen(false)}
            style={{ position: "fixed", inset: 0, zIndex: 45, background: "rgba(13,12,10,0.45)" }}
          />
        )}
        {/* ─── SIDEBAR ─── */}
        <aside
          className="shrink-0 flex flex-col"
          style={{
            width: 208,
            borderRight: `1px solid ${BB.border}`,
            background: BB.bg,
            ...(isMobile ? {
              position: "fixed", top: 0, bottom: 0, left: 0, zIndex: 50,
              transform: navOpen ? "translateX(0)" : "translateX(-100%)",
              transition: "transform 0.18s cubic-bezier(0.2, 0.7, 0.3, 1)",
              boxShadow: navOpen ? "8px 0 32px rgba(0,0,0,0.35)" : "none",
            } : {}),
          }}
        >
```

- [ ] **Step 6: Close drawer on nav interaction** — directly inside the aside, the nav list container is:

```jsx
          <div className="flex-1 overflow-y-auto py-4">
```

Change to close the drawer when any nav button inside is tapped (event bubbles up; harmless on desktop where `navOpen` is already false):

```jsx
          <div className="flex-1 overflow-y-auto py-4" onClick={() => setNavOpen(false)}>
```

- [ ] **Step 7: Mirror + build + manual check**

```bash
cp "C:/Users/peter/OneDrive/Desktop/Claude/middle-office-tools/src/TradeBookingForm.jsx" "C:/Users/peter/OneDrive/Desktop/Claude/trade-booking/src/TradeBookingForm.jsx"
cd "C:/Users/peter/OneDrive/Desktop/Claude/middle-office-tools" && npm run build
```
Expected: exit 0. Manual: at 390px the hamburger opens/closes the drawer over a backdrop and main is full-width; at 1280px nothing changed.

- [ ] **Step 8: Commit both repos** (messages: `feat(mobile): responsive sidebar drawer + hamburger`, with the Co-Authored-By footer; same two-repo pattern as Task 0 Step 5).

---

## Task 2: VIP LTV live monitoring panel → mobile layout

**Goal:** On mobile, reflow the VIP panel (header wraps, headline metrics stack) and render the collateral basket as stacked per-asset cards instead of a 6-column table. Desktop unchanged.

**Files:**
- Modify: MO `TradeBookingForm.jsx` — `LoanEnquiry` (add `isMobile`, ~8103); panel header (~8703); headline grid (~8835); collateral table (~8898–8959)
- Mirror: TB

**Acceptance Criteria:**
- [ ] At 390px: header actions wrap; Loan/Collateral/Borrowable stack to one column; collateral shows one card per asset (asset + value header; Qty / Current px / MC px / Liq px grid); a Total collateral row; tapping an asset opens the simulator focused on it.
- [ ] Desktop: existing table + 3-col headline unchanged.
- [ ] Build passes; MO/TB identical.

**Verify:** `npm run build` → exit 0; manual at 390px (cards render, tap → simulator) and 1280px (table unchanged).

**Steps:**

- [ ] **Step 1: Add `isMobile` to LoanEnquiry** — find `function LoanEnquiry({ onSelect, onHistory, BB, refreshSignal }) {` (~line 8103) and as its first body line add:

```jsx
  const isMobile = useIsMobile();
```

- [ ] **Step 2: Wrap the panel header** — the header strip style (~8703) is:

```jsx
            <div style={{
              padding: "8px 12px",
              borderBottom: "1px solid var(--rule)",
              background: "var(--paper-2)",
              display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8,
            }}>
```

Add wrapping so the action buttons drop to a second row on narrow widths:

```jsx
            <div style={{
              padding: "8px 12px",
              borderBottom: "1px solid var(--rule)",
              background: "var(--paper-2)",
              display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8,
              flexWrap: "wrap", rowGap: 6,
            }}>
```

- [ ] **Step 3: Reflow the headline metrics grid** — (~8835):

```jsx
                <div style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
                  borderBottom: "1px solid var(--rule)",
                }}>
```

becomes:

```jsx
                <div style={{
                  display: "grid",
                  gridTemplateColumns: isMobile ? "1fr" : "repeat(3, minmax(0, 1fr))",
                  borderBottom: "1px solid var(--rule)",
                }}>
```

And each metric cell (~8845) switches its divider from a right-border to a bottom-border on mobile:

```jsx
                    <div key={m.label} style={{
                      padding: "10px 12px",
                      borderRight: i < 2 ? "1px solid var(--rule)" : "none",
                    }}>
```

becomes:

```jsx
                    <div key={m.label} style={{
                      padding: "10px 12px",
                      borderRight: !isMobile && i < 2 ? "1px solid var(--rule)" : "none",
                      borderBottom: isMobile && i < 2 ? "1px solid var(--rule)" : "none",
                    }}>
```

- [ ] **Step 4: Collateral table → cards on mobile** — the collateral `<table>` block (~8898) begins with `<table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>` and ends at its closing `</table>` (~8959, just before the `{d.detail_error && (` block). Wrap the WHOLE table in a mobile conditional. Immediately before `<table …>` insert:

```jsx
                {isMobile ? (
                  <div style={{ padding: 8, display: "flex", flexDirection: "column", gap: 8 }}>
                    {(d.collateral || []).map((c) => (
                      <div key={c.asset} style={{
                        border: "1px solid var(--rule)", borderRadius: 3,
                        background: "var(--paper)", padding: "8px 10px",
                      }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6 }}>
                          <button
                            type="button"
                            onClick={() => openVipSim(c.asset)}
                            title={`Simulate — adjust ${c.asset} qty`}
                            style={{
                              border: "none", background: "transparent", padding: 0, cursor: "pointer",
                              color: "var(--ink)", fontWeight: 600, fontSize: 13,
                              textDecoration: "underline", textDecorationStyle: "dotted",
                              textUnderlineOffset: 3, textDecorationColor: "var(--ink-4)",
                            }}
                          >{c.asset}</button>
                          <span style={{ color: "var(--ink)", fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
                            {fmtUsd(c.value, 0)}
                          </span>
                        </div>
                        <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "4px 12px", fontSize: 11 }}>
                          <span style={{ color: "var(--ink-3)" }}>Qty</span>
                          <span style={{ textAlign: "right", color: "var(--ink-2)", fontVariantNumeric: "tabular-nums" }}>{fmtNum(c.qty, 6)}</span>
                          <span style={{ color: "var(--ink-3)" }}>Current px</span>
                          <span style={{ textAlign: "right", color: "var(--ink-2)", fontVariantNumeric: "tabular-nums" }}>{fmtUsd(c.price, c.price >= 100 ? 2 : 4)}</span>
                          <span style={{ color: "var(--ink-3)" }}>MC px · 77%</span>
                          <span style={{ textAlign: "right", color: c.mc_price == null ? "var(--ink-4)" : "#e8730c", fontVariantNumeric: "tabular-nums" }}>{c.mc_price == null ? "—" : fmtUsd(c.mc_price, c.mc_price >= 100 ? 2 : 4)}</span>
                          <span style={{ color: "var(--ink-3)" }}>Liq px · 91%</span>
                          <span style={{ textAlign: "right", color: c.liq_price == null ? "var(--ink-4)" : "var(--signal-sell)", fontVariantNumeric: "tabular-nums" }}>{c.liq_price == null ? "—" : fmtUsd(c.liq_price, c.liq_price >= 100 ? 2 : 4)}</span>
                        </div>
                      </div>
                    ))}
                    <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 10px", borderTop: "1px solid var(--rule)", fontWeight: 600 }}>
                      <span style={{ color: "var(--ink-3)", textTransform: "uppercase", letterSpacing: "0.06em", fontSize: 10 }}>Total collateral</span>
                      <span style={{ color: "var(--ink)", fontVariantNumeric: "tabular-nums" }}>{fmtUsd(d.summary && d.summary.collateral_raw_value, 0)}</span>
                    </div>
                  </div>
                ) : (
```

Then immediately AFTER the table's closing `</table>` add the closing of the ternary:

```jsx
                )}
```

NOTE: `fmtUsd`, `fmtNum`, and `openVipSim` are already in scope in this panel (the existing table uses `fmtUsd`; `fmtNum` is defined locally in the panel IIFE; `openVipSim` is the LoanEnquiry callback). If `fmtUsd` turns out NOT to be in the panel's scope at build time, use `fmtNum`-style formatting already present — but the existing table at this location already calls `fmtUsd`, so it is in scope.

- [ ] **Step 5: Mirror + build + manual check** (same mirror/build commands as Task 1 Step 7). Manual: at 390px the collateral renders as cards and tapping an asset opens the simulator focused on it; at 1280px the table is unchanged.

- [ ] **Step 6: Commit both repos** (`feat(mobile): VIP LTV live panel — stacked collateral cards`, Co-Authored-By footer, two-repo pattern).

---

## Task 3: ModalShell full-screen sheet + simulator headline/triggers reflow

**Goal:** Add an opt-in `mobileFullScreen` prop to `ModalShell` (full-screen on mobile, other modals unaffected); pass it from the simulator; reflow the simulator's headline (4→2 cols) and trigger detail (2→1 col) and let its header wrap.

**Files:**
- Modify: MO `TradeBookingForm.jsx` — `ModalShell` (~2748–2825); `VipCollateralSimulatorModal` (`isMobile`, ~7674; header ~7837; headline grid ~7888; ModalShell call ~7834; trigger grid ~8073)
- Mirror: TB

**Acceptance Criteria:**
- [ ] At 390px: tapping Simulate opens a full-screen sheet (fills viewport); headline shows 2 columns; trigger detail shows 1 column; header actions (Reset/Copy) wrap.
- [ ] Other modals (booking form, history, loan schedule) are unchanged on mobile (still the centered modal) — `mobileFullScreen` defaults off.
- [ ] Desktop simulator unchanged.
- [ ] Build passes; MO/TB identical.

**Verify:** `npm run build` → exit 0; manual at 390px (sheet fills screen, opens another modal e.g. Loan Schedule to confirm it is still a centered modal) and 1280px (unchanged).

**Steps:**

- [ ] **Step 1: Add the prop + full-screen branch to ModalShell** — signature (~2748):

```jsx
function ModalShell({ open, onClose, children, variant = "modal" }) {
```

becomes:

```jsx
function ModalShell({ open, onClose, children, variant = "modal", mobileFullScreen = false }) {
  const isMobile = useIsMobile();
```

(Insert `const isMobile = useIsMobile();` as the first body line — `useIsMobile` is a hoisted function declaration so it is callable here.)

- [ ] **Step 2: Compute the full-screen flag** — after `const isDrawer = variant === "drawer";` (~2776) add:

```jsx
  const fullScreen = isMobile && mobileFullScreen && !isDrawer;
```

- [ ] **Step 3: Use it in wrapperTop + wrapperStyle** — `const wrapperTop = isDrawer ? 0 : 80;` (~2789) becomes:

```jsx
  const wrapperTop = (isDrawer || fullScreen) ? 0 : 80;
```

In `wrapperStyle` (~2791) the `padding` line `padding: isDrawer ? 0 : 16,` becomes:

```jsx
    padding: (isDrawer || fullScreen) ? 0 : 16,
```

- [ ] **Step 4: Use it in panelStyle** — the modal (non-drawer) branch of `panelStyle` (~2817) currently:

```jsx
    : {
        width: "min(95vw, 1600px)",
        background: "var(--paper-2)",
        border: "1px solid var(--rule-2)",
        boxShadow: "0 16px 48px rgba(0,0,0,0.3)",
        opacity: mounted ? 1 : 0,
        transform: mounted ? "translateY(0)" : "translateY(-8px)",
        transition: "opacity 160ms ease-out, transform 160ms ease-out",
      };
```

becomes:

```jsx
    : fullScreen
    ? {
        width: "100vw",
        height: "100dvh",
        maxWidth: "none",
        background: "var(--paper-2)",
        border: "none",
        opacity: mounted ? 1 : 0,
        transform: mounted ? "translateY(0)" : "translateY(12px)",
        transition: "opacity 160ms ease-out, transform 160ms ease-out",
        overflow: "auto",
      }
    : {
        width: "min(95vw, 1600px)",
        background: "var(--paper-2)",
        border: "1px solid var(--rule-2)",
        boxShadow: "0 16px 48px rgba(0,0,0,0.3)",
        opacity: mounted ? 1 : 0,
        transform: mounted ? "translateY(0)" : "translateY(-8px)",
        transition: "opacity 160ms ease-out, transform 160ms ease-out",
      };
```

- [ ] **Step 5: Add `isMobile` to the simulator + pass the prop** — in `VipCollateralSimulatorModal` (~7674) add as first body line:

```jsx
  const isMobile = useIsMobile();
```

Then its `<ModalShell open={open} onClose={onClose}>` (~7834) becomes:

```jsx
    <ModalShell open={open} onClose={onClose} mobileFullScreen>
```

- [ ] **Step 6: Wrap the simulator header** — header style (~7837):

```jsx
        <div style={{
          padding: "14px 18px", borderBottom: "1px solid var(--rule)",
          display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12,
        }}>
```

becomes:

```jsx
        <div style={{
          padding: "14px 18px", borderBottom: "1px solid var(--rule)",
          display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12,
          flexWrap: "wrap", rowGap: 8,
        }}>
```

- [ ] **Step 7: Reflow the headline readouts grid** — (~7888):

```jsx
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
          borderBottom: "1px solid var(--rule)", background: "var(--paper-2)",
        }}>
```

becomes:

```jsx
        <div style={{
          display: "grid",
          gridTemplateColumns: isMobile ? "repeat(2, minmax(0, 1fr))" : "repeat(4, minmax(0, 1fr))",
          borderBottom: "1px solid var(--rule)", background: "var(--paper-2)",
        }}>
```

(Cell right-borders are left as-is; on a 2-col grid they read as light internal dividers — acceptable.)

- [ ] **Step 8: Reflow the trigger detail grid** — (~8073):

```jsx
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
          borderTop: "1px solid var(--rule)",
        }}>
```

becomes:

```jsx
        <div style={{
          display: "grid",
          gridTemplateColumns: isMobile ? "1fr" : "repeat(2, minmax(0, 1fr))",
          borderTop: "1px solid var(--rule)",
        }}>
```

And the trigger cell (~8081) `borderRight: i === 0 ? "1px solid var(--rule)" : "none"` becomes:

```jsx
            <div key={cell.label} style={{ padding: "9px 14px",
              borderRight: !isMobile && i === 0 ? "1px solid var(--rule)" : "none",
              borderBottom: isMobile && i === 0 ? "1px solid var(--rule)" : "none" }}>
```

- [ ] **Step 9: Mirror + build + manual check** (mirror/build commands as before). Manual: at 390px Simulate opens a full-screen sheet with 2-col headline + 1-col triggers; open another modal (e.g. Loan Schedule via a deal_ref) to confirm it is STILL the centered modal (prop defaults off). At 1280px the simulator is unchanged.

- [ ] **Step 10: Commit both repos** (`feat(mobile): full-screen simulator sheet + reflow headline/triggers`, footer, two-repo pattern).

---

## Task 4: Simulator editable collateral → stacked cards

**Goal:** On mobile, replace the simulator's 9-column editable table with one editable card per asset — the **Adjust (+/−) input** prominent — plus the "+ Add asset" button and Total. Desktop table unchanged.

**Files:**
- Modify: MO `TradeBookingForm.jsx` — simulator editable basket (~7946–8070)
- Mirror: TB

**Acceptance Criteria:**
- [ ] At 390px: each collateral asset is a card with a clearly tappable Adjust input; editing it updates New qty / Value / Simulated LTV / buffers live; Current qty / Price / MC px / Liq px shown; added rows expose SYMBOL + Price inputs; remove (✕) works; "+ Add asset" + Total render below; focused asset is highlighted.
- [ ] Desktop: existing editable table unchanged.
- [ ] Build passes; MO/TB identical.

**Verify:** `npm run build` → exit 0; manual at 390px (edit Adjust → Sim LTV moves; add/remove asset works) and 1280px (table unchanged).

**Steps:**

- [ ] **Step 1: Wrap the editable basket scroller** — the basket opens (~7946):

```jsx
        {/* ─── Editable collateral basket ─── */}
        <div style={{ maxHeight: "48vh", overflow: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
```

Replace the wrapper `<div>` and insert the mobile card branch BEFORE the `<table>`:

```jsx
        {/* ─── Editable collateral basket ─── */}
        <div style={{ maxHeight: isMobile ? "none" : "48vh", overflow: isMobile ? "visible" : "auto" }}>
          {isMobile ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 8, padding: 10 }}>
              {simRows.map((r, i) => {
                const c = sim.rows[i] || {};
                const focused = focusAsset && r.asset === focusAsset;
                const delta = Number(r.deltaQty) || 0;
                const deltaColor = delta > 0 ? "var(--signal-buy)" : delta < 0 ? "var(--signal-sell)" : "var(--ink-2)";
                return (
                  <div key={r.id} style={{
                    border: focused ? "1px solid var(--signal-link)" : "1px solid var(--rule)",
                    borderLeft: focused ? "3px solid var(--signal-link)" : "3px solid transparent",
                    borderRadius: 3,
                    background: focused ? "var(--signal-link-bg, rgba(31,99,234,0.06))" : "var(--paper)",
                    padding: "8px 10px",
                  }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                      {r.added ? (
                        <input
                          value={r.asset}
                          placeholder="SYMBOL"
                          onChange={(e) => setAsset(r.id, e.target.value)}
                          style={{ ...inputStyle, textAlign: "left", textTransform: "uppercase", width: 120 }}
                        />
                      ) : (
                        <span style={{ fontWeight: 600, color: "var(--ink)" }}>
                          {r.asset}
                          {!r.volatile && <span style={{ color: "var(--ink-4)", marginLeft: 6, fontSize: 10 }}>stable</span>}
                        </span>
                      )}
                      <button
                        type="button"
                        onClick={() => removeRow(r.id)}
                        title="Remove from scenario"
                        style={{ border: "none", background: "transparent", cursor: "pointer", color: "var(--ink-4)", padding: 2, display: "inline-flex", alignItems: "center" }}
                      ><X size={15} /></button>
                    </div>
                    <div style={{ marginBottom: 8 }}>
                      <div style={{ fontSize: 10, color: "var(--ink-3)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 3 }}>Adjust (+/−)</div>
                      <input
                        type="text"
                        inputMode="decimal"
                        value={vipGroupNum(r.deltaQty)}
                        placeholder="0"
                        onChange={onNum((v) => updateRow(r.id, { deltaQty: v }))}
                        style={{ ...inputStyle, textAlign: "left", fontSize: 15, padding: "8px 10px", color: deltaColor, fontWeight: delta !== 0 ? 600 : 400 }}
                      />
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "5px 12px", fontSize: 11 }}>
                      <span style={{ color: "var(--ink-3)" }}>Current qty</span>
                      <span style={{ textAlign: "right", color: "var(--ink-3)", fontVariantNumeric: "tabular-nums" }}>{r.added ? "—" : fmtQty(r.baseQty)}</span>
                      <span style={{ color: "var(--ink-3)" }}>New qty</span>
                      <span style={{ textAlign: "right", color: "var(--ink)", fontWeight: 500, fontVariantNumeric: "tabular-nums" }}>{fmtQty(c.qty)}</span>
                      <span style={{ color: "var(--ink-3)" }}>Price</span>
                      <span style={{ textAlign: "right", color: "var(--ink-2)", fontVariantNumeric: "tabular-nums" }}>
                        {r.added ? (
                          <input
                            type="text"
                            inputMode="decimal"
                            value={vipGroupNum(r.price)}
                            placeholder="price"
                            onChange={onNum((v) => updateRow(r.id, { price: v }))}
                            style={inputStyle}
                          />
                        ) : fmtPx(r.price)}
                      </span>
                      <span style={{ color: "var(--ink-3)" }}>Value</span>
                      <span style={{ textAlign: "right", color: "var(--ink)", fontVariantNumeric: "tabular-nums" }}>{fmtUsd(c.value, 0)}</span>
                      <span style={{ color: "var(--ink-3)" }}>MC px</span>
                      <span style={{ textAlign: "right", color: c.mc_price == null ? "var(--ink-4)" : "#e8730c", fontVariantNumeric: "tabular-nums" }}>{c.mc_price == null ? "—" : fmtPx(c.mc_price)}</span>
                      <span style={{ color: "var(--ink-3)" }}>Liq px</span>
                      <span style={{ textAlign: "right", color: c.liq_price == null ? "var(--ink-4)" : "var(--signal-sell)", fontVariantNumeric: "tabular-nums" }}>{c.liq_price == null ? "—" : fmtPx(c.liq_price)}</span>
                    </div>
                  </div>
                );
              })}
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: 4 }}>
                <button
                  type="button"
                  onClick={addRow}
                  style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "6px 12px", cursor: "pointer", border: "1px dashed var(--rule-2)", borderRadius: 3, background: "var(--paper)", color: "var(--ink-2)", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em" }}
                >+ Add asset</button>
                <span style={{ fontWeight: 600, color: "var(--ink)", fontVariantNumeric: "tabular-nums" }}>Total {fmtUsd(sim.rawCollateral, 0)}</span>
              </div>
            </div>
          ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
```

- [ ] **Step 2: Close the ternary** — find the basket table's closing `</table>` (~8069, immediately before `{/* ─── Trigger detail + disclaimer ─── */}`). It currently is:

```jsx
          </table>
        </div>
```

Change to close the `isMobile ? … : ( … )` ternary opened in Step 1:

```jsx
          </table>
          )}
        </div>
```

(`inputStyle`, `vipGroupNum`, `onNum`, `updateRow`, `removeRow`, `setAsset`, `addRow`, `fmtQty`, `fmtPx`, `fmtUsd`, `sim`, `simRows`, `focusAsset` are all already defined in the simulator component scope — reused as-is.)

- [ ] **Step 3: Mirror + build + manual check** (mirror/build commands as before). Manual at 390px: edit an Adjust value → New qty / Value / Simulated LTV / buffers update; "+ Add asset" adds an editable card with SYMBOL + Price inputs; ✕ removes; focused asset (opened from a qty tap) is highlighted. At 1280px the editable table is unchanged.

- [ ] **Step 4: Commit both repos** (`feat(mobile): simulator editable collateral as stacked cards`, footer, two-repo pattern).

---

## Task 5: Phase-1 verification pass

**Goal:** End-to-end manual confirmation of the whole Phase-1 flow on a phone viewport, plus a desktop regression sweep.

**Files:** none (verification only).

**Acceptance Criteria:**
- [ ] At 390px: hamburger → drawer → Loan Enquiry → VIP card reads top-to-bottom with collateral cards → tap Simulate → full-screen sheet → edit Adjust (LTV/buffers move) → Add asset / Reset / Copy / ✕ all work.
- [ ] At 1280px: shell, VIP panel table, and simulator are visually identical to `main` (spot-check against a second tab on `main`).
- [ ] `npm run build` exits 0; `diff MO TB` identical.
- [ ] `loanSearch.test.mjs` still runs clean: `node --test src/loanSearch.test.mjs` (no import breakage).

**Verify:**

```bash
cd "C:/Users/peter/OneDrive/Desktop/Claude/middle-office-tools"
npm run build
node --test src/loanSearch.test.mjs
diff "src/TradeBookingForm.jsx" "C:/Users/peter/OneDrive/Desktop/Claude/trade-booking/src/TradeBookingForm.jsx" && echo IDENTICAL
```

**Steps:**

- [ ] **Step 1:** Run the three commands above; all pass / IDENTICAL.
- [ ] **Step 2:** Walk the 390px flow in DevTools emulation per the acceptance criteria; note any defect and loop back to the owning task.
- [ ] **Step 3:** Desktop regression spot-check at 1280px.
- [ ] **Step 4:** If all green, Phase 1 is ready. (Shipping `trade-booking` later still needs the manual `python scripts/update_version.py` + chore commit per project convention — a release step, not part of this plan.)

---

## Self-Review (author checklist — completed)

- **Spec coverage:** useIsMobile (T0) ✓ · shell drawer (T1) ✓ · VIP live panel reflow + collateral cards (T2) ✓ · ModalShell full-screen sheet + simulator headline/triggers (T3) ✓ · simulator editable collateral cards (T4) ✓ · verification (T5) ✓. Phase-2 items (blotters/filters/KPIs/pagination) are intentionally a separate plan.
- **Placeholders:** none — every code step shows full code.
- **Type/name consistency:** `useIsMobile`/`isMobile`, `mobileFullScreen`, `fullScreen`, `navOpen`/`setNavOpen` used consistently; reused handlers (`openVipSim`, `updateRow`, `removeRow`, `setAsset`, `addRow`, `onNum`, `vipGroupNum`, `inputStyle`, `fmtUsd`, `fmtNum`, `fmtQty`, `fmtPx`) match their definitions in the existing code.
- **Scope:** single shippable unit (the VIP card + the shell needed to reach it).
