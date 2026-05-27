# Trade Booking UI · Claude Code Prompt

Paste the block below into Claude Code (or any IDE coding assistant). It assumes the developer has opened this `design_handoff_trade_booking/` folder so the assistant can read the reference files.

---

## Prompt

```
You are implementing a UI redesign for the Tokka Labs Trade Management System.

CONTEXT
The current product is a back-office trade booking application for an
institutional crypto desk. It has these screens today:
  - Deal Enquiry (the blotter — main view of all bookings)
  - Loan Enquiry
  - Pending Bookings (drafts awaiting approval)
  - Create Deal (a full-screen modal form)
  - User Admin / API Tokens

A design review proposed layout updates to these existing screens — no
new features, no new pages. The redesign lives in this handoff folder.

WHAT I WANT YOU TO DO
1. Read `README.md` and `STYLE_GUIDE.md` end-to-end first.
2. Read `tokens.css` (or `tokens.json`) — these are the canonical design
   tokens. Wire them into the codebase's existing token system; do not
   hard-code hex values in components.
3. Open the HTML prototypes in `references/` and visually compare
   against the current production screens. The differences are the
   work.
4. Implement the changes screen-by-screen, in this order:
     a. Deal Enquiry blotter
     b. Pending Bookings (renamed/restyled from current panel)
     c. Audit trail peek (new component for the existing clock-icon row affordance)
     d. Create Deal — convert from full-screen modal to right-side drawer
5. Match the typography pairing exactly: Source Serif 4 for page
   titles and section headers, JetBrains Mono for everything else.
6. Match the visual rules in STYLE_GUIDE.md — square corners (2-3px
   radius max), 1px hairline borders not box-shadows, dense 28px rows,
   status colour stays consistent wherever the status appears.

WHAT NOT TO DO
- Do not introduce pre-trade risk checks (counterparty exposure,
  sanctions, concentration). They are out of scope.
- Do not introduce live exposure / position panels. Out of scope.
- Do not invent new pages. Every change maps to a screen that already
  exists in the app.
- Do not hand-draw SVG iconography. Use the existing icon library; if
  one isn't present, use Lucide or Phosphor.
- Do not change the brand mark or the dark top chrome bar — those are
  intentionally preserved.

WORKFLOW
Before you write any code, summarise back to me:
  (a) the existing component / file you are about to modify,
  (b) the specific changes from the prototype,
  (c) which design tokens you'll consume.

Then implement one screen at a time. After each screen, show me the
diff and a screenshot before moving on.

Use the codebase's existing component library, state management, and
routing patterns. The HTML files in references/ are demonstrations of
intended look — they are not production code to lift directly.
```

---

That's the whole prompt. The handoff folder it points at contains:

- `README.md` — overview, fidelity, screen-by-screen implementation notes
- `STYLE_GUIDE.md` — detailed visual spec: tokens, typography, spacing, components
- `tokens.css` and `tokens.json` — design tokens, ready to import
- `references/` — the HTML prototypes, viewable in any browser
