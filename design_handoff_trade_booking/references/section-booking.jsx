// Section 3 — Proposed booking drawer.
// Side panel over the blotter (60% width), inline validation,
// pre-trade checks panel, live notional, position context.

const { TK, Pill, KV, Note, Spark } = window;

function FieldLabel({ children, required, hint }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 4 }}>
      <span className="tk-label" style={{ color: TK.ink2 }}>
        {children}{required && <span style={{ color: TK.sell, marginLeft: 3 }}>*</span>}
      </span>
      {hint && <span className="tk-mono" style={{ fontSize: 10, color: TK.ink3 }}>{hint}</span>}
    </div>
  );
}

function FieldInput({ value, placeholder, error, suffix, prefix, mono=true, num=false, w }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center',
      border: `1px solid ${error ? TK.err : TK.rule2}`, background: TK.paper,
      borderRadius: TK.radius, padding: '0 8px',
      boxShadow: error ? `inset 0 0 0 1px ${TK.err}` : 'none',
      width: w,
    }}>
      {prefix && <span className="tk-mono" style={{ color: TK.ink3, fontSize: 11, marginRight: 6 }}>{prefix}</span>}
      <div className={mono ? 'tk-mono' : ''} style={{
        flex: 1, padding: '7px 0', fontSize: 12, color: value ? TK.ink : TK.ink4,
        fontVariantNumeric: num ? 'tabular-nums' : 'normal',
      }}>
        {value || placeholder}
      </div>
      {suffix && <span className="tk-mono" style={{ color: TK.ink3, fontSize: 11, marginLeft: 6 }}>{suffix}</span>}
    </div>
  );
}

function FieldError({ children }) {
  if (!children) return null;
  return (
    <div className="tk-mono" style={{ fontSize: 10.5, color: TK.err, marginTop: 4, display: 'flex', alignItems: 'center', gap: 5 }}>
      <span style={{ width: 12, height: 12, borderRadius: '50%', background: TK.err, color: TK.paper, fontSize: 9, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700 }}>!</span>
      {children}
    </div>
  );
}

function CheckRow({ tone, label, detail, action }) {
  const map = {
    ok:    { dot: TK.buy,   glyph: '✓', label: 'PASS' },
    amber: { dot: TK.warn,  glyph: '⚠', label: 'WARN' },
    red:   { dot: TK.sell,  glyph: '✕', label: 'BLOCK' },
    info:  { dot: TK.ink3,  glyph: 'i', label: 'INFO' },
  };
  const m = map[tone] || map.info;
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '24px 70px 1fr auto',
      gap: 8, padding: '8px 0', borderBottom: `1px solid ${TK.rule}`, alignItems: 'center',
    }}>
      <div style={{
        width: 20, height: 20, borderRadius: 2, background: m.dot,
        color: TK.paper, fontSize: 11, fontWeight: 700,
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      }}>{m.glyph}</div>
      <div className="tk-mono" style={{ fontSize: 10, color: m.dot, fontWeight: 600, letterSpacing: '0.06em' }}>{m.label}</div>
      <div>
        <div className="tk-mono" style={{ fontSize: 12, color: TK.ink, fontWeight: 500 }}>{label}</div>
        {detail && <div className="tk-mono" style={{ fontSize: 11, color: TK.ink3, marginTop: 2 }}>{detail}</div>}
      </div>
      {action && <button className="tk-btn" style={{ fontSize: 10, padding: '4px 8px' }}>{action}</button>}
    </div>
  );
}

function ProposedBookingDrawer() {
  return (
    <div className="tk" style={{ width: 1920, height: 1180, background: TK.paper, position: 'relative', overflow: 'hidden' }}>
      {/* Faint backdrop of the blotter (just header strip suggesting context preserved) */}
      <div style={{ position: 'absolute', inset: 0, background: TK.paper2, opacity: 0.55 }}>
        <div style={{ height: 44, background: TK.panel, opacity: 0.4 }} />
        <div style={{ padding: 24, color: TK.ink4, fontSize: 36, fontFamily: TK.serif }}>Deal Enquiry</div>
        <div style={{ padding: '0 24px' }}>
          {[1,2,3,4,5,6,7,8,9].map(i => (
            <div key={i} style={{ height: 30, borderBottom: `1px solid ${TK.rule}`, opacity: 0.4 }} />
          ))}
        </div>
      </div>
      <div style={{ position: 'absolute', inset: 0, background: 'rgba(13,12,10,0.18)' }} />

      {/* Drawer */}
      <div style={{
        position: 'absolute', top: 0, right: 0, bottom: 0,
        width: 1180, background: TK.paper, boxShadow: '-20px 0 60px rgba(0,0,0,0.18)',
        display: 'flex', flexDirection: 'column',
      }}>
        {/* Drawer header */}
        <div style={{ padding: '16px 24px 12px', borderBottom: `1px solid ${TK.rule2}`, display: 'flex', alignItems: 'center', gap: 14 }}>
          <div style={{ flex: 1 }}>
            <div className="tk-mono" style={{ fontSize: 11, color: TK.ink3, marginBottom: 2 }}>NEW DEAL · DRAFT MFX-00000042</div>
            <div className="tk-serif" style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.01em' }}>Book a Spot Trade</div>
          </div>
          <div style={{ display: 'flex', gap: 0, border: `1px solid ${TK.rule2}`, borderRadius: TK.radius, overflow: 'hidden' }}>
            {['Spot', 'Futures', 'Cashflow', 'Loan', 'Other'].map((t, i) => (
              <button key={t} className="tk-mono" style={{
                padding: '6px 14px', fontSize: 11, border: 'none',
                background: i === 0 ? TK.ink : 'transparent',
                color: i === 0 ? TK.paper : TK.ink2,
                borderRight: i < 4 ? `1px solid ${TK.rule2}` : 'none',
                textTransform: 'uppercase', letterSpacing: '0.05em', cursor: 'pointer',
                fontWeight: i === 0 ? 600 : 500,
              }}>{t}</button>
            ))}
          </div>
          <button className="tk-btn" style={{ padding: '6px 10px' }}>↗ Open full</button>
          <button className="tk-btn" style={{ padding: '6px 10px', fontWeight: 600 }}>✕</button>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflow: 'auto', display: 'grid', gridTemplateColumns: '1fr 380px' }}>
          {/* Left: form */}
          <div style={{ padding: '18px 24px', borderRight: `1px solid ${TK.rule}` }}>
            {/* Section: Trade Summary */}
            <div style={{ marginBottom: 22 }}>
              <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 12 }}>
                <div className="tk-serif" style={{ fontSize: 15, fontWeight: 600 }}>◆ Trade Summary</div>
                <div className="tk-mono" style={{ fontSize: 10, color: TK.ink3 }}>step 1 of 3</div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
                <div>
                  <FieldLabel hint="auto · editable">Internal Trade ID</FieldLabel>
                  <FieldInput value="MFX-00000042" />
                </div>
                <div>
                  <FieldLabel hint="optional">External Trade ID</FieldLabel>
                  <FieldInput placeholder="exchange order id / cp ref / 0x…" />
                </div>
                <div>
                  <FieldLabel required hint="UTC">Trade Date</FieldLabel>
                  <FieldInput value="27/05/2026 02:43:00" prefix="📅" />
                </div>
                <div>
                  <FieldLabel required hint="T+2 default">Value Date</FieldLabel>
                  <FieldInput value="29/05/2026 02:43:00" prefix="📅" />
                </div>
                <div>
                  <FieldLabel required>Portfolio</FieldLabel>
                  <FieldInput value="8000 · Primary Market Making" />
                </div>
                <div>
                  <FieldLabel hint="auto from portfolio">Entity</FieldLabel>
                  <FieldInput value="Tokka Labs Pte Ltd" />
                </div>
                <div style={{ gridColumn: 'span 2' }}>
                  <FieldLabel required>Counterparty</FieldLabel>
                  <FieldInput value="Binance Cayman" suffix="◑ Internal" />
                </div>
              </div>
            </div>

            {/* Section: Trade Details */}
            <div style={{ marginBottom: 22 }}>
              <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 12 }}>
                <div className="tk-serif" style={{ fontSize: 15, fontWeight: 600 }}>◆ Trade Details</div>
                <div className="tk-mono" style={{ fontSize: 10, color: TK.ink3 }}>step 2 of 3</div>
              </div>

              {/* Direction toggle */}
              <div style={{ marginBottom: 14 }}>
                <FieldLabel required>Direction</FieldLabel>
                <div style={{ display: 'flex', gap: 0, border: `1px solid ${TK.rule2}`, borderRadius: TK.radius, width: 'fit-content', overflow: 'hidden' }}>
                  <button className="tk-mono" style={{
                    padding: '8px 24px', background: TK.buy, color: TK.paper, border: 'none', cursor: 'pointer',
                    fontSize: 12, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em',
                    display: 'flex', alignItems: 'center', gap: 6,
                  }}>▲ Long / Buy</button>
                  <button className="tk-mono" style={{
                    padding: '8px 24px', background: 'transparent', color: TK.ink2, border: 'none', cursor: 'pointer',
                    fontSize: 12, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em',
                    display: 'flex', alignItems: 'center', gap: 6, borderLeft: `1px solid ${TK.rule2}`,
                  }}>▼ Short / Sell</button>
                </div>
              </div>

              {/* Pair row */}
              <div style={{
                display: 'grid', gridTemplateColumns: '1fr 1.4fr 12px 1fr 1.4fr', gap: 10, alignItems: 'end',
                background: TK.paper2, padding: 14, borderRadius: TK.radius, marginBottom: 14,
              }}>
                <div>
                  <FieldLabel required>Base Asset</FieldLabel>
                  <FieldInput value="BTC · Bitcoin" />
                </div>
                <div>
                  <FieldLabel required hint="qty">Base Amount</FieldLabel>
                  <FieldInput value="12.500" num suffix="BTC" />
                </div>
                <div className="tk-serif" style={{ fontSize: 24, color: TK.ink3, textAlign: 'center', paddingBottom: 6 }}>×</div>
                <div>
                  <FieldLabel required>Quote Asset</FieldLabel>
                  <FieldInput value="USDT · Tether USD" />
                </div>
                <div>
                  <FieldLabel required hint="auto · editable">Quote Amount</FieldLabel>
                  <FieldInput value="744,250.00" num suffix="USDT" />
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 14, marginBottom: 14 }}>
                <div>
                  <FieldLabel required hint="quote / base">Price</FieldLabel>
                  <FieldInput value="59,540.00" num suffix="USDT/BTC" />
                </div>
                <div>
                  <FieldLabel>Fee Asset</FieldLabel>
                  <FieldInput value="USDT · Tether USD" />
                </div>
                <div>
                  <FieldLabel>Fee Amount</FieldLabel>
                  <FieldInput value="744.25" num suffix="USDT" />
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 14, marginBottom: 14 }}>
                <div>
                  <FieldLabel>Account Type</FieldLabel>
                  <FieldInput value="Exchange" />
                </div>
                <div>
                  <FieldLabel required>Account Name</FieldLabel>
                  <FieldInput value="binance-main-spot · sub-01" />
                </div>
              </div>

              <div>
                <FieldLabel hint="on-chain only">Tx Hash</FieldLabel>
                <FieldInput value="0xa7f3c1…d2ab" />
              </div>
            </div>

            {/* Section: Comments & Attachments */}
            <div>
              <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 12 }}>
                <div className="tk-serif" style={{ fontSize: 15, fontWeight: 600 }}>◆ Comments & Attachments</div>
                <div className="tk-mono" style={{ fontSize: 10, color: TK.ink3 }}>step 3 of 3</div>
              </div>
              <FieldLabel>Notes</FieldLabel>
              <div style={{ border: `1px solid ${TK.rule2}`, padding: '8px 10px', borderRadius: TK.radius, minHeight: 60, background: TK.paper }}>
                <div className="tk-mono" style={{ fontSize: 12, color: TK.ink2 }}>
                  Hedge against ECHOCREEK ETH loan drawdown · ref MLA00000012.
                </div>
              </div>
              <div style={{
                marginTop: 12, border: `1.5px dashed ${TK.rule2}`, padding: 18, textAlign: 'center', borderRadius: TK.radius,
                background: TK.paper, color: TK.ink3,
              }}>
                <div style={{ fontSize: 14, marginBottom: 4 }}>↥</div>
                <div className="tk-mono" style={{ fontSize: 11 }}>Drop term sheet · invoice · screenshot · or <span className="tk-link">click to browse</span></div>
                <div className="tk-mono" style={{ fontSize: 10, color: TK.ink4, marginTop: 4 }}>PDF · DOCX · IMG · uploads to Drive on submit</div>
              </div>
              <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                <Pill tone="muted">📎 term-sheet-binance.pdf · 142KB</Pill>
              </div>
            </div>
          </div>

          {/* Right: comments preview + live JSON */}
          <div style={{ padding: '18px 18px', background: TK.paper, display: 'flex', flexDirection: 'column', gap: 18 }}>
            {/* Compact summary card */}
            <div style={{ background: TK.paper2, padding: '12px 14px', borderLeft: `3px solid ${TK.confirmed}` }}>
              <div className="tk-label" style={{ marginBottom: 6 }}>Draft summary</div>
              <div className="tk-serif" style={{ fontSize: 16, fontWeight: 600, letterSpacing: '-0.005em', marginBottom: 4 }}>
                Long · BTC 12.500 × USDT 744,250
              </div>
              <div className="tk-mono" style={{ fontSize: 11, color: TK.ink2, lineHeight: 1.55 }}>
                @ 59,540 USDT/BTC · fee 744.25 USDT (10 bps)<br />
                <span style={{ color: TK.ink3 }}>portfolio</span> <b>8000 PMM</b> · <span style={{ color: TK.ink3 }}>cp</span> <b>Binance Cayman</b><br />
                <span style={{ color: TK.ink3 }}>trade</span> <b>27/05 02:43 UTC</b> · <span style={{ color: TK.ink3 }}>value</span> <b>29/05 (T+2)</b>
              </div>
            </div>

            {/* Live JSON — promoted to fill the column */}
            <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <div className="tk-serif" style={{ fontSize: 14, fontWeight: 600 }}>◆ Live record</div>
                <div className="tk-mono" style={{ fontSize: 10, color: TK.ink3 }}>JSON · POST /api/bookings</div>
                <div style={{ flex: 1 }} />
                <button className="tk-btn" style={{ padding: '3px 8px', fontSize: 10 }}>⧉ Copy</button>
                <button className="tk-btn" style={{ padding: '3px 8px', fontSize: 10 }}>Diff</button>
              </div>
              <div style={{
                background: TK.panel, color: TK.panelInk, padding: 14, fontSize: 11, lineHeight: 1.6,
                fontFamily: TK.mono, borderRadius: TK.radius, overflow: 'auto', flex: 1,
              }}>
                <div><span style={{ color: '#9a9384' }}>{'{'}</span></div>
                <div style={{ paddingLeft: 14 }}><span style={{ color: '#f5c97a' }}>"deal_ref"</span>: <span style={{ color: '#bce4cf' }}>"MFX-00000042"</span>,</div>
                <div style={{ paddingLeft: 14 }}><span style={{ color: '#f5c97a' }}>"external_trade_id"</span>: <span style={{ color: '#9a9384' }}>null</span>,</div>
                <div style={{ paddingLeft: 14 }}><span style={{ color: '#f5c97a' }}>"txn_type"</span>: <span style={{ color: '#bce4cf' }}>"SPOT"</span>,</div>
                <div style={{ paddingLeft: 14 }}><span style={{ color: '#f5c97a' }}>"direction"</span>: <span style={{ color: '#bce4cf' }}>"LONG"</span>,</div>
                <div style={{ paddingLeft: 14 }}><span style={{ color: '#f5c97a' }}>"entity"</span>: <span style={{ color: '#bce4cf' }}>"Tokka Labs Pte Ltd"</span>,</div>
                <div style={{ paddingLeft: 14 }}><span style={{ color: '#f5c97a' }}>"portfolio_id"</span>: <span style={{ color: '#d4dff1' }}>8000</span>,</div>
                <div style={{ paddingLeft: 14 }}><span style={{ color: '#f5c97a' }}>"portfolio_name"</span>: <span style={{ color: '#bce4cf' }}>"PRIMARY MARKET MAKING"</span>,</div>
                <div style={{ paddingLeft: 14 }}><span style={{ color: '#f5c97a' }}>"counterparty"</span>: <span style={{ color: '#bce4cf' }}>"BINANCE CAYMAN"</span>,</div>
                <div style={{ paddingLeft: 14 }}><span style={{ color: '#f5c97a' }}>"counterparty_id"</span>: <span style={{ color: '#d4dff1' }}>4012</span>,</div>
                <div style={{ paddingLeft: 14 }}><span style={{ color: '#f5c97a' }}>"account"</span>: <span style={{ color: '#bce4cf' }}>"binance-main-spot · sub-01"</span>,</div>
                <div style={{ paddingLeft: 14 }}><span style={{ color: '#f5c97a' }}>"account_type"</span>: <span style={{ color: '#bce4cf' }}>"EXCHANGE"</span>,</div>
                <div style={{ paddingLeft: 14 }}><span style={{ color: '#f5c97a' }}>"base_asset"</span>: <span style={{ color: '#bce4cf' }}>"BTC"</span>,</div>
                <div style={{ paddingLeft: 14 }}><span style={{ color: '#f5c97a' }}>"base_amount"</span>: <span style={{ color: '#d4dff1' }}>12.5</span>,</div>
                <div style={{ paddingLeft: 14 }}><span style={{ color: '#f5c97a' }}>"quote_asset"</span>: <span style={{ color: '#bce4cf' }}>"USDT"</span>,</div>
                <div style={{ paddingLeft: 14 }}><span style={{ color: '#f5c97a' }}>"quote_amount"</span>: <span style={{ color: '#d4dff1' }}>744250</span>,</div>
                <div style={{ paddingLeft: 14 }}><span style={{ color: '#f5c97a' }}>"price"</span>: <span style={{ color: '#d4dff1' }}>59540</span>,</div>
                <div style={{ paddingLeft: 14 }}><span style={{ color: '#f5c97a' }}>"fee_asset"</span>: <span style={{ color: '#bce4cf' }}>"USDT"</span>,</div>
                <div style={{ paddingLeft: 14 }}><span style={{ color: '#f5c97a' }}>"fee_amount"</span>: <span style={{ color: '#d4dff1' }}>744.25</span>,</div>
                <div style={{ paddingLeft: 14 }}><span style={{ color: '#f5c97a' }}>"trade_date"</span>: <span style={{ color: '#bce4cf' }}>"2026-05-27T02:43:00Z"</span>,</div>
                <div style={{ paddingLeft: 14 }}><span style={{ color: '#f5c97a' }}>"value_date"</span>: <span style={{ color: '#bce4cf' }}>"2026-05-29T02:43:00Z"</span>,</div>
                <div style={{ paddingLeft: 14 }}><span style={{ color: '#f5c97a' }}>"txid_reference"</span>: <span style={{ color: '#bce4cf' }}>"0xa7f3c1…d2ab"</span>,</div>
                <div style={{ paddingLeft: 14 }}><span style={{ color: '#f5c97a' }}>"user_id"</span>: <span style={{ color: '#bce4cf' }}>"danny.pang"</span>,</div>
                <div style={{ paddingLeft: 14 }}><span style={{ color: '#f5c97a' }}>"status"</span>: <span style={{ color: '#bce4cf' }}>"DRAFT"</span>,</div>
                <div style={{ paddingLeft: 14 }}><span style={{ color: '#f5c97a' }}>"comment"</span>: <span style={{ color: '#bce4cf' }}>"Hedge against ECHOCREEK ETH loan drawdown · ref MLA00000012."</span>,</div>
                <div style={{ paddingLeft: 14 }}><span style={{ color: '#f5c97a' }}>"_meta"</span>: <span style={{ color: '#9a9384' }}>{'{ "attachments": ["term-sheet-binance.pdf"] }'}</span></div>
                <div><span style={{ color: '#9a9384' }}>{'}'}</span></div>
              </div>
              <div className="tk-mono" style={{ fontSize: 10, color: TK.ink3, marginTop: 6, padding: '4px 6px', background: TK.paper2, display: 'flex', justifyContent: 'space-between' }}>
                <span>MOD <b style={{ color: TK.ink2 }}>02:43:00 UTC</b></span>
                <span>ATT <b style={{ color: TK.ink2 }}>1</b></span>
                <span>CAT <b style={{ color: TK.confirmed }}>SPOT</b></span>
              </div>
            </div>
          </div>
        </div>

        {/* Footer CTA */}
        <div style={{
          borderTop: `2px solid ${TK.ink}`, padding: '12px 24px',
          display: 'flex', alignItems: 'center', gap: 14, background: TK.paper2,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span className="tk-dot" style={{ background: TK.buy, width: 8, height: 8 }} />
            <span className="tk-mono" style={{ fontSize: 11, color: TK.ink2 }}>0 errors · ready to submit</span>
          </div>
          <div style={{ flex: 1 }} />
          <span className="tk-mono" style={{ fontSize: 11, color: TK.ink3 }}>
            Modified <b style={{ color: TK.ink }}>02:43:00 UTC</b> · 1 attachment
          </span>
          <button className="tk-btn">Reset</button>
          <button className="tk-btn">Save Draft <span className="tk-kbd" style={{ marginLeft: 6 }}>⌘S</span></button>
          <button className="tk-btn tk-btn-primary" style={{ padding: '8px 18px', fontWeight: 600 }}>
            Generate Output <span className="tk-kbd" style={{ marginLeft: 6, background: 'rgba(255,255,255,0.15)', borderColor: 'rgba(255,255,255,0.25)', color: TK.paper }}>⌘↵</span>
          </button>
        </div>
      </div>

      {/* Annotations */}
      <Note x={780} y={120} w={300} side="left">
        <b>1. Drawer, not full-screen modal.</b> Operators keep context.
        Backdrop hints at the blotter still being there.
      </Note>
      <Note x={20} y={510} w={280} side="right">
        <b>2. Inline validation.</b> Errors and hints sit next to the field
        they refer to — not in a list at the bottom of the form.
      </Note>
      <Note x={1640} y={170} w={260} side="left">
        <b>3. Draft summary card.</b> One-glance read of what's being booked
        — saves re-scrolling the form to confirm before submit.
      </Note>
      <Note x={1640} y={500} w={260} side="left">
        <b>4. Live record, promoted.</b> The JSON pane gets the right column
        in full — easier to scan, with a copy + diff affordance.
      </Note>
      <Note x={420} y={1140} w={340} side="bot">
        <b>5. Footer keeps state visible.</b> Error count, mod-time, attachments
        on the bar above the CTA. Submit is decisive, not "5 issues found".
      </Note>
    </div>
  );
}

Object.assign(window, { ProposedBookingDrawer });
