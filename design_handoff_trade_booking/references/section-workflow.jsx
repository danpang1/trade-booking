// Section 4 — Maker-checker approval queue + audit-history peek + position view.
// Shows three side-by-side artboards demonstrating workflows the
// current UI hints at but doesn't fully express.

const { TK, Pill, KV, Stat, Note, Spark } = window;

// ── Pending Bookings — redesigned ─────────────────────────────────────────
function ApprovalQueue() {
  const items = [
    { ref: 'MFX-00000042', t: 'SPOT', dir: 'LONG', maker: 'danny.pang', age: '00:04',
      cp: 'Binance Cayman', body: 'BTC 12.500 × USDT 744,250 @ 59,540' },
    { ref: 'MFX-00000041', t: 'CASHFLOW', dir: 'PAID', maker: 'irven.heng', age: '00:18',
      cp: 'Bebop Ltd', body: 'BTC 0.31438 · interest expense' },
  ];
  const recent = [
    { ref: 'MFX-00000040', dec: 'approved', by: 'peter', when: '17:38', t: 'SPOT' },
    { ref: 'MFX-00000039', dec: 'approved', by: 'peter', when: '17:35', t: 'SPOT' },
    { ref: 'MFX-00000038', dec: 'rejected', by: 'peter', when: '17:11', t: 'CASHFLOW', note: 'Wrong portfolio · resubmit on 8888' },
    { ref: 'MFX-00000037', dec: 'approved', by: 'peter', when: '17:11', t: 'CASHFLOW' },
    { ref: 'MFX-00000036', dec: 'approved', by: 'peter', when: '14:26', t: 'CASHFLOW' },
  ];

  return (
    <div className="tk" style={{ width: 760, minHeight: 880, background: TK.paper, display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '14px 20px 10px', borderBottom: `1px solid ${TK.rule}` }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
          <div className="tk-serif" style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.01em' }}>Pending Bookings</div>
          <div style={{ display: 'flex', gap: 0, border: `1px solid ${TK.rule2}`, borderRadius: TK.radius, overflow: 'hidden' }}>
            {['Pending 2', 'Approved 11', 'Rejected 1'].map((t, i) => (
              <button key={t} className="tk-mono" style={{
                padding: '5px 12px', fontSize: 11, border: 'none',
                background: i === 0 ? TK.ink : 'transparent',
                color: i === 0 ? TK.paper : TK.ink2,
                borderRight: i < 2 ? `1px solid ${TK.rule2}` : 'none',
                textTransform: 'uppercase', letterSpacing: '0.05em', cursor: 'pointer',
                fontWeight: i === 0 ? 600 : 500,
              }}>{t}</button>
            ))}
          </div>
        </div>
        <div className="tk-mono" style={{ fontSize: 11, color: TK.ink3, marginTop: 6 }}>
          Drafts created by makers · awaiting approval before settlement
        </div>
      </div>

      <div style={{ padding: '14px 20px' }}>
        <div className="tk-label" style={{ marginBottom: 8 }}>Awaiting action · 2</div>
        {items.map((it, i) => (
          <div key={it.ref} style={{
            background: TK.paper2, border: `1px solid ${TK.rule2}`, borderLeft: `3px solid ${TK.confirmed}`,
            padding: 14, marginBottom: 10, borderRadius: TK.radius,
          }}>
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 8 }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
                <span className="tk-mono tk-link" style={{ fontSize: 13, fontWeight: 600 }}>{it.ref}</span>
                <Pill tone="muted">{it.t}</Pill>
                <Pill tone={it.dir === 'LONG' ? 'buy' : 'sell'}>{it.dir}</Pill>
              </div>
              <div className="tk-mono" style={{ fontSize: 11, color: TK.ink3 }}>
                submitted <b style={{ color: TK.ink }}>{it.age}</b> ago by <b style={{ color: TK.ink }}>{it.maker}</b>
              </div>
            </div>
            <div className="tk-mono" style={{ fontSize: 13, color: TK.ink, marginBottom: 6 }}>
              {it.body}
            </div>
            <div className="tk-mono" style={{ fontSize: 11, color: TK.ink3, marginBottom: 12 }}>
              counterparty <b style={{ color: TK.ink2 }}>{it.cp}</b> · settle <b style={{ color: TK.ink2 }}>T+2</b>
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <button className="tk-btn tk-btn-primary" style={{ flex: 1 }}>
                ✓ Approve <span className="tk-kbd" style={{ marginLeft: 6, background: 'rgba(255,255,255,0.15)', borderColor: 'rgba(255,255,255,0.25)', color: TK.paper }}>A</span>
              </button>
              <button className="tk-btn" style={{ flex: 1, color: TK.sell, borderColor: TK.sell }}>
                ✕ Reject <span className="tk-kbd" style={{ marginLeft: 6 }}>R</span>
              </button>
              <button className="tk-btn">↗ Open draft</button>
            </div>
          </div>
        ))}

        <div className="tk-label" style={{ margin: '18px 0 8px' }}>Recently decided</div>
        <div style={{ border: `1px solid ${TK.rule}`, borderRadius: TK.radius, overflow: 'hidden' }}>
          {recent.map((r, i) => (
            <div key={r.ref} style={{
              display: 'grid', gridTemplateColumns: '100px 100px 60px 80px 1fr',
              alignItems: 'center', padding: '8px 12px',
              borderBottom: i < recent.length - 1 ? `1px solid ${TK.rule}` : 'none',
              background: i % 2 === 1 ? 'rgba(0,0,0,0.015)' : 'transparent',
              fontSize: 11,
            }} className="tk-mono">
              <span className="tk-link">{r.ref}</span>
              <span>
                <Pill tone={r.dec === 'approved' ? 'settled' : 'cancelled'}>
                  {r.dec === 'approved' ? '✓ approved' : '✕ rejected'}
                </Pill>
              </span>
              <span style={{ color: TK.ink3 }}>{r.t}</span>
              <span style={{ color: TK.ink3 }}>{r.when}</span>
              <span style={{ color: TK.ink3 }}>
                by <b style={{ color: TK.ink2 }}>{r.by}</b>
                {r.note && <span> · "{r.note}"</span>}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Audit history peek ────────────────────────────────────────────────────
function AuditHistory() {
  const events = [
    { t: '17:42:18', who: 'system', kind: 'STATUS', from: 'CONFIRMED', to: 'PROCESSED', via: 'settlement-engine · job#48201' },
    { t: '14:23:55', who: 'peter',  kind: 'APPROVE', from: '—',         to: '—',         via: 'approval-queue · session 7a3e' },
    { t: '14:23:12', who: 'danny.pang', kind: 'EDIT', field: 'quote_amount', from: '744,000', to: '744,250' },
    { t: '14:23:08', who: 'danny.pang', kind: 'EDIT', field: 'notes', from: '', to: 'Hedge against ECHOCREEK ETH loan drawdown' },
    { t: '14:22:48', who: 'danny.pang', kind: 'ATTACH', file: 'term-sheet-binance.pdf', size: '142 KB' },
    { t: '14:22:00', who: 'danny.pang', kind: 'CREATE', via: 'POST /api/bookings · 192.168.4.21 · macOS · Chrome 124' },
  ];
  return (
    <div className="tk" style={{ width: 580, minHeight: 880, background: TK.paper, display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '14px 20px 10px', borderBottom: `1px solid ${TK.rule}` }}>
        <div className="tk-mono" style={{ fontSize: 10, color: TK.ink3, marginBottom: 2 }}>HISTORY · MFX-00000040</div>
        <div className="tk-serif" style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.01em' }}>Audit Trail</div>
        <div className="tk-mono" style={{ fontSize: 11, color: TK.ink3, marginTop: 4 }}>
          6 events · created 2026-05-26 14:22 by danny.pang · last 17:42 system
        </div>
      </div>

      <div style={{ padding: '18px 20px', position: 'relative' }}>
        {/* spine */}
        <div style={{ position: 'absolute', left: 36, top: 24, bottom: 24, width: 1, background: TK.rule2 }} />
        {events.map((e, i) => {
          const kindMap = {
            CREATE:   { c: TK.confirmed, label: 'created' },
            EDIT:     { c: TK.warn,      label: 'edited' },
            APPROVE:  { c: TK.buy,       label: 'approved' },
            STATUS:   { c: TK.processed, label: 'status' },
            ATTACH:   { c: TK.ink3,      label: 'attached' },
            REJECT:   { c: TK.sell,      label: 'rejected' },
          };
          const m = kindMap[e.kind];
          return (
            <div key={i} style={{ display: 'grid', gridTemplateColumns: '32px 1fr', gap: 12, marginBottom: 18, position: 'relative' }}>
              <div style={{
                width: 12, height: 12, borderRadius: '50%', background: m.c, marginTop: 4,
                marginLeft: 10, border: `2px solid ${TK.paper}`, boxShadow: `0 0 0 1px ${m.c}`,
              }} />
              <div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 4 }}>
                  <span className="tk-mono" style={{ fontSize: 11, color: TK.ink3, fontVariantNumeric: 'tabular-nums' }}>{e.t}</span>
                  <Pill tone="muted">{m.label}</Pill>
                  <span className="tk-mono" style={{ fontSize: 11, color: TK.ink }}>
                    by <b>{e.who}</b>
                  </span>
                </div>
                <div className="tk-mono" style={{ fontSize: 12, color: TK.ink2, lineHeight: 1.5 }}>
                  {e.kind === 'EDIT' && (
                    <>
                      <span style={{ color: TK.ink3 }}>field </span><b style={{ color: TK.ink }}>{e.field}</b>
                      <div style={{ marginTop: 4, display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{
                          padding: '2px 6px', background: TK.sellBg, color: TK.sell, textDecoration: 'line-through',
                          borderRadius: 2, fontSize: 11,
                        }}>{e.from || '∅'}</span>
                        <span style={{ color: TK.ink3 }}>→</span>
                        <span style={{
                          padding: '2px 6px', background: TK.buyBg, color: TK.buy,
                          borderRadius: 2, fontSize: 11,
                        }}>{e.to}</span>
                      </div>
                    </>
                  )}
                  {e.kind === 'STATUS' && (
                    <>
                      <span style={{ padding: '2px 6px', background: TK.confirmedBg, color: TK.confirmed, borderRadius: 2 }}>{e.from}</span>
                      <span style={{ color: TK.ink3 }}> → </span>
                      <span style={{ padding: '2px 6px', background: TK.processedBg, color: TK.processed, borderRadius: 2 }}>{e.to}</span>
                      <div style={{ marginTop: 4, fontSize: 10.5, color: TK.ink3 }}>{e.via}</div>
                    </>
                  )}
                  {e.kind === 'APPROVE' && (
                    <div style={{ fontSize: 10.5, color: TK.ink3 }}>{e.via}</div>
                  )}
                  {e.kind === 'CREATE' && (
                    <div style={{ fontSize: 10.5, color: TK.ink3 }}>{e.via}</div>
                  )}
                  {e.kind === 'ATTACH' && (
                    <span><b>{e.file}</b> <span style={{ color: TK.ink3 }}>· {e.size}</span></span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
        <div style={{
          marginTop: 12, padding: '10px 12px', background: TK.paper2,
          borderLeft: `3px solid ${TK.confirmed}`,
        }}>
          <div className="tk-label">Compliance export</div>
          <div className="tk-mono" style={{ fontSize: 11, color: TK.ink2, marginTop: 4 }}>
            Signed PDF · includes IP, user-agent, session, prev/next hash. <span className="tk-link">Generate report ↗</span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Position view ─────────────────────────────────────────────────────────
function PositionView() {
  const rows = [
    { asset: 'BTC',  qty: '32.184',    avg: '58,210.40', mkt: '59,612.00', pnl: '+45,116', pnlc: TK.buy, conc: 68,  cap: 50, breach: true },
    { asset: 'ETH',  qty: '420.50',    avg: '2,612.10',  mkt: '2,664.20',  pnl: '+21,907', pnlc: TK.buy, conc: 18,  cap: 30 },
    { asset: 'USDT', qty: '1,238,492', avg: '1.0000',    mkt: '1.0001',    pnl: '+124',    pnlc: TK.buy, conc: 14,  cap: 40 },
    { asset: 'USDC', qty: '802,341',   avg: '1.0000',    mkt: '0.9998',    pnl: '−160',    pnlc: TK.sell, conc: 9,   cap: 40 },
    { asset: 'SOL',  qty: '5,200',     avg: '142.30',    mkt: '139.80',    pnl: '−13,000', pnlc: TK.sell, conc: 6,   cap: 20 },
  ];
  return (
    <div className="tk" style={{ width: 580, minHeight: 880, background: TK.paper, display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '14px 20px 10px', borderBottom: `1px solid ${TK.rule}` }}>
        <div className="tk-mono" style={{ fontSize: 10, color: TK.ink3, marginBottom: 2 }}>POSITION · 8000 PRIMARY MARKET MAKING</div>
        <div className="tk-serif" style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.01em' }}>Live Exposure</div>
        <div className="tk-mono" style={{ fontSize: 11, color: TK.ink3, marginTop: 4 }}>
          marked 02:48:53 UTC · price feed: composite
        </div>
      </div>

      <div style={{ padding: '14px 20px', borderBottom: `1px solid ${TK.rule}`, display: 'flex', gap: 0 }}>
        <Stat label="Gross MV" value="$4.21M" sub="▲ 1.2% wow" tone={TK.confirmed} w={120} />
        <Stat label="Net" value="$3.81M" sub="long bias" tone={TK.buy} w={120} />
        <Stat label="Day P&L" value={<span style={{ color: TK.buy }}>+$53,987</span>} sub="+1.41%" tone={TK.buy} w={120} />
        <Stat label="VaR (1d 99%)" value="$182K" sub="4.3% of NAV" tone={TK.warn} w={140} />
      </div>

      <div style={{ flex: 1, padding: '14px 20px' }}>
        <div className="tk-label" style={{ marginBottom: 8 }}>By asset</div>
        <div className="tk-mono" style={{
          display: 'grid', gridTemplateColumns: '50px 100px 90px 90px 80px 1fr',
          fontSize: 10, color: TK.ink3, textTransform: 'uppercase', letterSpacing: '0.05em',
          padding: '6px 0', borderBottom: `1px solid ${TK.rule2}`,
        }}>
          <span>Asset</span>
          <span style={{ textAlign: 'right' }}>Qty</span>
          <span style={{ textAlign: 'right' }}>Avg</span>
          <span style={{ textAlign: 'right' }}>Mkt</span>
          <span style={{ textAlign: 'right' }}>P&L</span>
          <span style={{ paddingLeft: 12 }}>Concentration / cap</span>
        </div>
        {rows.map((r, i) => (
          <div key={r.asset} className="tk-mono" style={{
            display: 'grid', gridTemplateColumns: '50px 100px 90px 90px 80px 1fr',
            fontSize: 12, padding: '8px 0', borderBottom: `1px solid ${TK.rule}`, alignItems: 'center',
          }}>
            <span style={{ fontWeight: 600 }}>{r.asset}</span>
            <span className="tk-num" style={{ textAlign: 'right' }}>{r.qty}</span>
            <span className="tk-num" style={{ textAlign: 'right', color: TK.ink3 }}>{r.avg}</span>
            <span className="tk-num" style={{ textAlign: 'right', color: TK.ink2 }}>{r.mkt}</span>
            <span className="tk-num" style={{ textAlign: 'right', color: r.pnlc, fontWeight: 600 }}>{r.pnl}</span>
            <div style={{ paddingLeft: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ flex: 1, height: 8, background: TK.paper3, borderRadius: 2, position: 'relative', overflow: 'hidden' }}>
                <div style={{
                  position: 'absolute', left: 0, top: 0, bottom: 0,
                  width: `${Math.min(r.conc, 100)}%`,
                  background: r.breach ? TK.sell : (r.conc / r.cap > 0.7 ? TK.warn : TK.confirmed),
                }} />
                <div style={{ position: 'absolute', left: `${r.cap}%`, top: -2, bottom: -2, width: 1, background: TK.ink2 }} />
              </div>
              <span style={{ fontSize: 11, color: r.breach ? TK.sell : TK.ink3, minWidth: 56, textAlign: 'right' }}>
                {r.conc}% / {r.cap}%
              </span>
            </div>
          </div>
        ))}

        <div className="tk-label" style={{ marginTop: 18, marginBottom: 8 }}>By counterparty · exposure vs limit</div>
        {[
          ['Binance Cayman', 2410, 3000, true],
          ['1inch Fusion', 480, 1500],
          ['Bebop Ltd', 92, 500],
          ['Echocreek Ltd', 1840, 2000],
          ['Alternity Fund', 3120, 5000],
        ].map(([n, used, cap, near], i) => (
          <div key={n} style={{ display: 'grid', gridTemplateColumns: '160px 1fr 110px', alignItems: 'center', gap: 12, padding: '6px 0' }} className="tk-mono">
            <span style={{ fontSize: 12, color: TK.ink }}>{n}</span>
            <div style={{ height: 8, background: TK.paper3, borderRadius: 2, position: 'relative', overflow: 'hidden' }}>
              <div style={{
                position: 'absolute', left: 0, top: 0, bottom: 0,
                width: `${(used / cap) * 100}%`,
                background: used / cap > 0.85 ? TK.warn : TK.confirmed,
              }} />
            </div>
            <span className="tk-num" style={{ fontSize: 11, color: near ? TK.warn : TK.ink3, textAlign: 'right' }}>
              ${(used / 1000).toFixed(2)}M / ${(cap / 1000).toFixed(0)}M
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

Object.assign(window, { ApprovalQueue, AuditHistory, PositionView });
