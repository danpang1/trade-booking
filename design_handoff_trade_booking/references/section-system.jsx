// Section 5 — Design system shelf for the proposed direction.
// Type · color · status pills · density / row heights · components.

const { TK, Pill } = window;

function Swatch({ name, val, fg }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 120 }}>
      <div style={{ height: 56, background: val, border: `1px solid ${TK.rule}`, borderRadius: TK.radius,
                    display: 'flex', alignItems: 'flex-end', padding: 6, color: fg || TK.ink, fontSize: 10 }}
           className="tk-mono">{name}</div>
      <div className="tk-mono" style={{ fontSize: 10, color: TK.ink3 }}>{val}</div>
    </div>
  );
}

function DesignSystem() {
  return (
    <div className="tk" style={{ width: 1920, minHeight: 1100, background: TK.paper, padding: '24px 32px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 32 }}>
        {/* TYPE */}
        <div>
          <div className="tk-label" style={{ marginBottom: 6 }}>01 · Typography</div>
          <div className="tk-serif" style={{ fontSize: 28, fontWeight: 600, marginBottom: 18, letterSpacing: '-0.015em' }}>Two-family system</div>
          <div style={{ marginBottom: 18 }}>
            <div className="tk-mono" style={{ fontSize: 10, color: TK.ink3 }}>SOURCE SERIF 4 · headlines, page titles, drawer titles</div>
            <div className="tk-serif" style={{ fontSize: 42, fontWeight: 600, letterSpacing: '-0.02em', lineHeight: 1.05 }}>Deal Enquiry</div>
            <div className="tk-serif" style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.01em' }}>Book a Spot Trade</div>
            <div className="tk-serif" style={{ fontSize: 15, fontWeight: 600 }}>◆ Trade Summary</div>
          </div>
          <div>
            <div className="tk-mono" style={{ fontSize: 10, color: TK.ink3 }}>JETBRAINS MONO · everything else</div>
            <div className="tk-mono" style={{ fontSize: 13, fontWeight: 500 }}>MCF00000038 · BTC 12.500 × USDT 744,250</div>
            <div className="tk-mono" style={{ fontSize: 12 }}>Cashflow paid · counterparty Bebop Ltd</div>
            <div className="tk-label" style={{ fontSize: 10 }}>UPPERCASE LABELS · 10/11px</div>
            <div className="tk-mono" style={{ fontSize: 10, color: TK.ink3 }}>tertiary / hint · 10px</div>
          </div>
          <div style={{ marginTop: 22, padding: '10px 14px', background: TK.paper2, borderLeft: `3px solid ${TK.ink}` }}>
            <div className="tk-mono" style={{ fontSize: 11, color: TK.ink2, lineHeight: 1.6 }}>
              <b>Rule.</b> Serif for human-readable identity (page titles, section headers).
              Mono for everything operators read positionally — numbers, refs, codes, tabular
              data. Never mix them in the same span.
            </div>
          </div>
        </div>

        {/* COLOR */}
        <div>
          <div className="tk-label" style={{ marginBottom: 6 }}>02 · Color</div>
          <div className="tk-serif" style={{ fontSize: 28, fontWeight: 600, marginBottom: 18, letterSpacing: '-0.015em' }}>Paper, ink, and signals</div>

          <div className="tk-mono" style={{ fontSize: 10, color: TK.ink3, marginBottom: 6 }}>SURFACE</div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
            <Swatch name="paper" val={TK.paper} />
            <Swatch name="paper2" val={TK.paper2} />
            <Swatch name="paper3" val={TK.paper3} />
            <Swatch name="panel" val={TK.panel} fg={TK.panelInk} />
          </div>

          <div className="tk-mono" style={{ fontSize: 10, color: TK.ink3, marginBottom: 6 }}>INK</div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
            <Swatch name="ink" val={TK.ink} fg={TK.paper} />
            <Swatch name="ink2" val={TK.ink2} fg={TK.paper} />
            <Swatch name="ink3" val={TK.ink3} fg={TK.paper} />
            <Swatch name="ink4" val={TK.ink4} fg={TK.paper} />
          </div>

          <div className="tk-mono" style={{ fontSize: 10, color: TK.ink3, marginBottom: 6 }}>SEMANTIC</div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
            <Swatch name="buy / settled" val={TK.buy} fg={TK.paper} />
            <Swatch name="sell / err" val={TK.sell} fg={TK.paper} />
            <Swatch name="warn" val={TK.warn} fg={TK.paper} />
            <Swatch name="confirmed" val={TK.confirmed} fg={TK.paper} />
          </div>
          <div style={{ marginTop: 16, padding: '10px 14px', background: TK.paper2, borderLeft: `3px solid ${TK.warn}` }}>
            <div className="tk-mono" style={{ fontSize: 11, color: TK.ink2, lineHeight: 1.6 }}>
              <b>Rule.</b> Saturation is reserved for signal — buy/sell, status, risk.
              Chrome stays in paper + ink. Resist the urge to add a brand accent
              for decoration: it dilutes the signal value.
            </div>
          </div>
        </div>

        {/* DENSITY + STATUS */}
        <div>
          <div className="tk-label" style={{ marginBottom: 6 }}>03 · Density & State</div>
          <div className="tk-serif" style={{ fontSize: 28, fontWeight: 600, marginBottom: 18, letterSpacing: '-0.015em' }}>Tighter rows, clearer states</div>

          <div className="tk-mono" style={{ fontSize: 10, color: TK.ink3, marginBottom: 6 }}>ROW HEIGHTS</div>
          <div style={{ border: `1px solid ${TK.rule}`, marginBottom: 16 }}>
            <div style={{ height: 28, padding: '0 12px', borderBottom: `1px solid ${TK.rule}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }} className="tk-mono">
              <span style={{ fontSize: 12 }}>28px · dense blotter (default)</span>
              <span className="tk-num" style={{ fontSize: 11, color: TK.ink3 }}>~38 rows / 1080px</span>
            </div>
            <div style={{ height: 36, padding: '0 12px', borderBottom: `1px solid ${TK.rule}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }} className="tk-mono">
              <span style={{ fontSize: 12 }}>36px · comfortable</span>
              <span className="tk-num" style={{ fontSize: 11, color: TK.ink3 }}>~28 rows</span>
            </div>
            <div style={{ height: 52, padding: '0 12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }} className="tk-mono">
              <span style={{ fontSize: 12 }}>52px · cards / cashflow ledger</span>
              <span className="tk-num" style={{ fontSize: 11, color: TK.ink3 }}>~19 rows</span>
            </div>
          </div>

          <div className="tk-mono" style={{ fontSize: 10, color: TK.ink3, marginBottom: 6 }}>STATUS PILLS</div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 16 }}>
            <Pill tone="pending" dot>Pending</Pill>
            <Pill tone="confirmed" dot>Confirmed</Pill>
            <Pill tone="processed" dot>Processed</Pill>
            <Pill tone="settled" dot>Settled</Pill>
            <Pill tone="cancelled" dot>Cancelled</Pill>
            <Pill tone="buy">▲ Long</Pill>
            <Pill tone="sell">▼ Short</Pill>
            <Pill tone="warn">⚠ Limit breach</Pill>
            <Pill tone="err">✕ Rejected</Pill>
            <Pill tone="muted">Internal</Pill>
          </div>

          <div className="tk-mono" style={{ fontSize: 10, color: TK.ink3, marginBottom: 6 }}>BUTTONS</div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 16 }}>
            <button className="tk-btn tk-btn-primary">Submit for Approval</button>
            <button className="tk-btn">Secondary</button>
            <button className="tk-btn" style={{ color: TK.sell, borderColor: TK.sell }}>Reject</button>
            <button className="tk-btn" style={{ padding: '4px 8px', fontSize: 10 }}>tiny</button>
          </div>

          <div className="tk-mono" style={{ fontSize: 10, color: TK.ink3, marginBottom: 6 }}>KEYBOARD</div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 16 }}>
            <span><span className="tk-kbd">⌘K</span> command palette</span>
            <span><span className="tk-kbd">B</span> new booking</span>
            <span><span className="tk-kbd">A</span> approve</span>
            <span><span className="tk-kbd">R</span> reject</span>
            <span><span className="tk-kbd">/</span> search</span>
            <span><span className="tk-kbd">J</span>/<span className="tk-kbd">K</span> nav row</span>
            <span><span className="tk-kbd">⌘↵</span> submit</span>
          </div>

          <div style={{ padding: '10px 14px', background: TK.paper2, borderLeft: `3px solid ${TK.confirmed}` }}>
            <div className="tk-mono" style={{ fontSize: 11, color: TK.ink2, lineHeight: 1.6 }}>
              <b>Rule.</b> Square corners (2–3px radius max). Borders, not shadows.
              1px hairlines on cream — never grey on grey. Status colour stays the
              same wherever the status appears (pill, dot, row border, footer chart).
            </div>
          </div>
        </div>
      </div>

      {/* Component shelf — table of mini examples */}
      <div style={{ marginTop: 36 }}>
        <div className="tk-label" style={{ marginBottom: 6 }}>04 · Patterns to keep using</div>
        <div className="tk-serif" style={{ fontSize: 22, fontWeight: 600, marginBottom: 16, letterSpacing: '-0.01em' }}>Shelf</div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 16 }}>
          {/* Inline ref link */}
          <div style={{ padding: 14, background: TK.paper2, borderRadius: TK.radius }}>
            <div className="tk-mono" style={{ fontSize: 10, color: TK.ink3, marginBottom: 8 }}>REF LINK</div>
            <div className="tk-mono" style={{ fontSize: 13 }}>
              <span className="tk-link">MCF00000038</span>
              <div style={{ fontSize: 10, color: TK.ink3 }}>↳ MCF00000037</div>
            </div>
          </div>
          {/* KPI tile */}
          <div style={{ padding: 14, background: TK.paper2, borderRadius: TK.radius }}>
            <div className="tk-mono" style={{ fontSize: 10, color: TK.ink3, marginBottom: 8 }}>KPI TILE</div>
            <div style={{ borderLeft: `3px solid ${TK.confirmed}`, paddingLeft: 10 }}>
              <div className="tk-label">Notional · open</div>
              <div className="tk-mono tk-num" style={{ fontSize: 18, fontWeight: 600 }}>$4.21M</div>
              <div className="tk-mono" style={{ fontSize: 10, color: TK.ink3 }}>▲ 1.2% wow</div>
            </div>
          </div>
          {/* Filter chip */}
          <div style={{ padding: 14, background: TK.paper2, borderRadius: TK.radius }}>
            <div className="tk-mono" style={{ fontSize: 10, color: TK.ink3, marginBottom: 8 }}>FILTER CHIP</div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              <button className="tk-mono" style={{ padding: '4px 10px', border: `1px solid ${TK.ink}`, background: TK.ink, color: TK.paper, borderRadius: 2, fontSize: 11, textTransform: 'uppercase' }}>Pending 6</button>
              <button className="tk-mono" style={{ padding: '4px 10px', border: `1px solid ${TK.rule2}`, background: 'transparent', color: TK.ink2, borderRadius: 2, fontSize: 11, textTransform: 'uppercase' }}>Settled 14</button>
            </div>
          </div>
          {/* Diff */}
          <div style={{ padding: 14, background: TK.paper2, borderRadius: TK.radius }}>
            <div className="tk-mono" style={{ fontSize: 10, color: TK.ink3, marginBottom: 8 }}>FIELD DIFF</div>
            <div className="tk-mono" style={{ fontSize: 11, display: 'flex', gap: 6, alignItems: 'center' }}>
              <span style={{ padding: '2px 6px', background: TK.sellBg, color: TK.sell, textDecoration: 'line-through' }}>744,000</span>
              <span style={{ color: TK.ink3 }}>→</span>
              <span style={{ padding: '2px 6px', background: TK.buyBg, color: TK.buy }}>744,250</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { DesignSystem });
