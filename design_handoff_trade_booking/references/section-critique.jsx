// Section 1 — Critique panels (text) + the original blotter screenshot
// with annotation callouts pinned to real coordinates.

const { TK, Pill, Note } = window;

function CritiquePanel({ title, items, tone }) {
  return (
    <div className="tk" style={{ width: 600, padding: '24px 28px', background: TK.paper, height: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
        <span className="tk-dot" style={{ background: tone, width: 10, height: 10 }} />
        <span className="tk-label" style={{ fontSize: 11, color: TK.ink2 }}>{tone === TK.buy ? 'Strengths' : 'Gaps · Opportunities'}</span>
      </div>
      <div className="tk-serif" style={{ fontSize: 28, fontWeight: 600, letterSpacing: '-0.015em', marginBottom: 20 }}>
        {title}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {items.map((it, i) => (
          <div key={i} style={{ borderLeft: `2px solid ${tone}`, paddingLeft: 14 }}>
            <div className="tk-mono" style={{ fontSize: 11, color: TK.ink3, marginBottom: 4 }}>
              {String(i + 1).padStart(2, '0')} · {it.tag}
            </div>
            <div className="tk-serif" style={{ fontSize: 15, fontWeight: 600, marginBottom: 4, letterSpacing: '-0.005em' }}>
              {it.head}
            </div>
            <div className="tk-mono" style={{ fontSize: 12, color: TK.ink2, lineHeight: 1.55 }}>
              {it.body}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Strengths() {
  return (
    <CritiquePanel title="What's already right" tone={TK.buy} items={[
      { tag: 'Aesthetic',  head: 'The mono + cream identity is a real asset',
        body: 'Most trade-ops UIs default to enterprise-grey SaaS. Your typographic system reads like a printed trade ticket — it signals seriousness without being cold. Keep this; institutionalise it further.' },
      { tag: 'Information', head: 'Live JSON pane on the booking form',
        body: 'Showing the raw record alongside the form is a power-user move and back-office operators love it. Make it collapsible, add a Diff view when editing, and you have a feature most vendors don\'t ship.' },
      { tag: 'Workflow',   head: 'Pending Bookings as a separate queue',
        body: 'The conceptual seed of a maker-checker workflow is already here. Lean into it — make it a first-class four-eyes approval queue with role gates and timers.' },
      { tag: 'Schema',     head: 'Deal types are sensibly scoped',
        body: 'Cashflow / Loan / Spot / Futures covers the common shapes. Surface deal-type as a filter chip row above the table — right now it\'s buried in the Details column.' },
      { tag: 'Refs',       head: 'Deal references are stable & human-readable',
        body: 'MCF00000038 / MLA00000011 with cross-linking between deals is exactly right. Promote the link affordance — make hovering a ref show a peek card with the linked deal.' },
    ]} />
  );
}

function Gaps() {
  return (
    <CritiquePanel title="Where to push" tone={TK.sell} items={[
      { tag: 'Density',   head: 'Rows are 2× too tall for an institutional blotter',
        body: 'Calypso/Murex/Front Arena fit 30–50 rows per viewport. You\'re showing ~14. Tighten row height to 28px, drop the per-row history icon into a hover affordance, and free that vertical space for filter chips + footer aggregations.' },
      { tag: 'Theming',   head: 'Three different visual systems on screen at once',
        body: 'Cream main / black sidebar / dark-themed Admin panel. Pick one direction — I\'d keep cream for read views and use a dark inset only for the booking drawer (focus mode). The User Admin screen should match the blotter.' },
      { tag: 'Validation',head: 'Errors only surface at the bottom of a long form',
        body: 'After scrolling through Spot Summary → Spot Details → Comments, the validation list appears far from the offending fields. Move errors inline next to each field, and gate the Generate Output CTA with a count of remaining issues.' },
      { tag: 'Modal',     head: 'Booking form takes over the entire screen',
        body: 'Operators book in context — they reference the previous trade, check the previous booking, then book. A right-side drawer (60% width) over a still-visible blotter preserves context and reduces tab-switching.' },
      { tag: 'Columns',   head: 'The Details column is unstructured prose',
        body: '"PTF 8000 RFQ FUNDS PTF 8001 CLOB 88 ETH" packs five fields into one string. Break into structured columns: Direction · Amount · Asset · Venue · Tag. Make Details a hover-expanded note.' },
      { tag: 'Aggregates', head: 'No totals, no notional sum, no per-status counts',
        body: 'An ops blotter without a footer of rolling totals is missing its scorecard. Add: notional sum (toggle base/quote), count by status, oldest pending age, settlement due today.' },
      { tag: 'Audit',     head: 'History is hinted at but never shown',
        body: 'The clock icon in column 1 implies an audit trail exists. Surface it: a row click should open a peek with field-level history, who changed what, when, and from which IP/session.' },
      { tag: 'Keyboard',  head: 'No discoverable shortcuts or command palette',
        body: 'Cmd-K to jump to a deal, B for book, A for approve, / to focus search. Print a small keyboard legend in the chrome — power users will live in this app.' },
    ]} />
  );
}

Object.assign(window, { Strengths, Gaps });
