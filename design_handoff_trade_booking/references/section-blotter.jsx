// Section 2 — Proposed institutional-grade blotter.
// 1920 x 1080 artboard. Dense rows, saved views, structured columns,
// pre-trade KPI strip, footer aggregations, hover affordances.

const { TK, Pill, KV, Stat, Delta, Spark, Note } = window;

const DEALS = [
  { ref:'MCF00000041', t:'17:42:18', date:'2026-05-26', type:'CASHFLOW', dir:'PAID',  ptf:'8888', name:'TOKKA LABS · TREASURY',     cp:'BEBOP LTD',       base:'BTC',  amt:'0.31438', quote:'',     notional:'18,712.40 USD', status:'pending',   age:'00:04',  link:null,        venue:'OTC',         tag:'INTEREST EXPENSE', settle:'2026-05-26', risk:'ok' },
  { ref:'MCF00000040', t:'17:38:02', date:'2026-05-26', type:'SPOT',     dir:'LONG',  ptf:'8001', name:'CLOB',                       cp:'BINANCE',         base:'ETH',  amt:'88.000',   quote:'USDT', notional:'234,432.00 USDT', status:'confirmed', age:'00:08',  link:null,        venue:'CEX',         tag:'TRADE',            settle:'2026-05-28', risk:'ok' },
  { ref:'MCF00000039', t:'17:35:00', date:'2026-05-26', type:'SPOT',     dir:'SHORT', ptf:'8000', name:'PRIMARY MARKET MAKING',     cp:'1INCH FUSION',    base:'ETH',  amt:'88.000',   quote:'USDT', notional:'234,432.00 USDT', status:'confirmed', age:'00:11',  link:null,        venue:'DEX',         tag:'INTERNAL OFFSET',  settle:'2026-05-28', risk:'amber' },
  { ref:'MCF00000038', t:'17:12:44', date:'2026-05-26', type:'CASHFLOW', dir:'FUNDS', ptf:'8001', name:'CLOB',                       cp:'8000',            base:'ETH',  amt:'88.000',   quote:'',     notional:'234,432.00 USDT', status:'processed', age:'00:34',  link:'MCF00000037', venue:'INTERNAL',  tag:'RFQ FUNDING',      settle:'2026-05-26', risk:'ok' },
  { ref:'MCF00000037', t:'17:12:44', date:'2026-05-26', type:'CASHFLOW', dir:'FUNDS', ptf:'8000', name:'PRIMARY MARKET MAKING',     cp:'8001',            base:'ETH',  amt:'88.000',   quote:'',     notional:'234,432.00 USDT', status:'processed', age:'00:34',  link:'MCF00000038', venue:'INTERNAL',  tag:'PM FUNDING',       settle:'2026-05-26', risk:'ok' },
  { ref:'MCF00000036', t:'14:26:11', date:'2026-05-26', type:'CASHFLOW', dir:'RECV',  ptf:'8888', name:'TOKKA LABS · TREASURY',     cp:'ECHOCREEK LTD',   base:'ETH',  amt:'88.000',   quote:'',     notional:'234,432.00 USDT', status:'settled',   age:'03:20',  link:'MLA00000012', venue:'OTC',       tag:'LOAN DRAWDOWN',    settle:'2026-05-26', risk:'ok' },
  { ref:'MCF00000035', t:'14:23:47', date:'2026-05-26', type:'CASHFLOW', dir:'RECV',  ptf:'8888', name:'TOKKA LABS · TREASURY',     cp:'BEBOP LTD',       base:'USDC', amt:'999.00',   quote:'',     notional:'999.00 USD',     status:'settled',   age:'03:22',  link:null,        venue:'OTC',         tag:'OTHER INCOME',     settle:'2026-05-26', risk:'ok' },
  { ref:'MCF00000034', t:'12:20:00', date:'2026-05-26', type:'CASHFLOW', dir:'PAID',  ptf:'8888', name:'TOKKA LABS · TREASURY',     cp:'BEBOP LTD',       base:'USDC', amt:'88.00',    quote:'',     notional:'88.00 USD',      status:'settled',   age:'05:26',  link:null,        venue:'OTC',         tag:'OPEX',             settle:'2026-05-26', risk:'ok' },
  { ref:'MCF00000033', t:'04:30:55', date:'2026-05-25', type:'CASHFLOW', dir:'PAID',  ptf:'8000', name:'PRIMARY MARKET MAKING',     cp:'ALTERNITY FUND',  base:'BTC',  amt:'3.0000',   quote:'',     notional:'178,532.10 USD', status:'settled',   age:'1d',     link:'MLA00000011', venue:'OTC',       tag:'LOAN REPAYMENT',   settle:'2026-05-25', risk:'ok' },
  { ref:'MCF00000032', t:'04:24:18', date:'2026-05-25', type:'CASHFLOW', dir:'RECV',  ptf:'8000', name:'PRIMARY MARKET MAKING',     cp:'ALTERNITY FUND',  base:'BTC',  amt:'3.0000',   quote:'',     notional:'178,532.10 USD', status:'settled',   age:'1d',     link:'MLA00000011', venue:'OTC',       tag:'LOAN DRAWDOWN',    settle:'2026-05-25', risk:'ok' },
  { ref:'MCF00000031', t:'14:15:02', date:'2026-05-22', type:'CASHFLOW', dir:'FUNDS', ptf:'8001', name:'CLOB',                       cp:'8000',            base:'USDT', amt:'8,888.00', quote:'',     notional:'8,888.00 USD',   status:'cancelled', age:'5d',     link:null,        venue:'INTERNAL',  tag:'RFQ FUNDING',      settle:'—',          risk:'ok' },
  { ref:'MCF00000030', t:'14:15:02', date:'2026-05-22', type:'CASHFLOW', dir:'FUNDS', ptf:'8000', name:'PRIMARY MARKET MAKING',     cp:'8001',            base:'USDT', amt:'8,888.00', quote:'',     notional:'8,888.00 USD',   status:'cancelled', age:'5d',     link:null,        venue:'INTERNAL',  tag:'PM FUNDING',       settle:'—',          risk:'ok' },
  { ref:'MCF00000028', t:'08:55:30', date:'2026-05-20', type:'CASHFLOW', dir:'PAID',  ptf:'8888', name:'TOKKA LABS · TREASURY',     cp:'ALTERNITY FUND',  base:'BTC',  amt:'0.1048',   quote:'',     notional:'6,240.10 USD',   status:'settled',   age:'7d',     link:'MLA00000010', venue:'OTC',       tag:'INTEREST EXPENSE', settle:'2026-05-20', risk:'ok' },
  { ref:'MCF00000025', t:'08:06:22', date:'2026-05-20', type:'CASHFLOW', dir:'PAID',  ptf:'8888', name:'TOKKA LABS · TREASURY',     cp:'ALTERNITY FUND',  base:'BTC',  amt:'50.000',   quote:'',     notional:'2,975,500 USD',  status:'settled',   age:'7d',     link:'MLA00000010', venue:'OTC',       tag:'LOAN REPAYMENT',   settle:'2026-05-20', risk:'amber' },
  { ref:'MCF00000026', t:'08:02:11', date:'2026-05-20', type:'CASHFLOW', dir:'PAID',  ptf:'8888', name:'TOKKA LABS · TREASURY',     cp:'ALTERNITY FUND',  base:'BTC',  amt:'0.3144',   quote:'',     notional:'18,712.40 USD',  status:'settled',   age:'7d',     link:'MLA00000010', venue:'OTC',       tag:'INTEREST EXPENSE', settle:'2026-05-20', risk:'ok' },
  { ref:'MCF00000027', t:'08:02:11', date:'2026-05-20', type:'CASHFLOW', dir:'PAID',  ptf:'8888', name:'TOKKA LABS · TREASURY',     cp:'ALTERNITY FUND',  base:'BTC',  amt:'0.0489',   quote:'',     notional:'2,911.78 USD',   status:'settled',   age:'7d',     link:'MLA00000010', venue:'OTC',       tag:'INTEREST EXPENSE', settle:'2026-05-20', risk:'ok' },
  { ref:'MCF00000024', t:'08:55:00', date:'2026-05-19', type:'LOAN',     dir:'RECV',  ptf:'8000', name:'PRIMARY MARKET MAKING',     cp:'ECHOCREEK LTD',   base:'USDT', amt:'500,000',  quote:'',     notional:'500,000 USD',    status:'settled',   age:'8d',     link:null,        venue:'OTC',       tag:'OPEN POSITION',    settle:'2026-05-19', risk:'ok' },
  { ref:'MCF00000023', t:'08:50:14', date:'2026-05-19', type:'SPOT',     dir:'LONG',  ptf:'8000', name:'PRIMARY MARKET MAKING',     cp:'BINANCE',         base:'BTC',  amt:'12.500',   quote:'USDT', notional:'743,775.25 USDT',status:'settled',   age:'8d',     link:null,        venue:'CEX',       tag:'TRADE',            settle:'2026-05-21', risk:'ok' },
];

function StatusPillFor({ s }) {
  const map = { pending: 'pending', confirmed: 'confirmed', processed: 'processed', settled: 'settled', cancelled: 'cancelled' };
  return <Pill tone={map[s]}>{s}</Pill>;
}

function DirGlyph({ d }) {
  // long/short -> ▲/▼ ; paid/recv -> -/+ ; funds -> ⇄
  const long = d === 'LONG' || d === 'RECV';
  const short = d === 'SHORT' || d === 'PAID';
  const internal = d === 'FUNDS';
  const color = long ? TK.buy : short ? TK.sell : TK.ink2;
  const glyph = long ? '▲' : short ? '▼' : '⇄';
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color, fontWeight: 600 }}>
      <span style={{ fontSize: 10 }}>{glyph}</span>
      <span className="tk-mono" style={{ fontSize: 11 }}>{d}</span>
    </span>
  );
}

function Chip({ children, active, count, tone }) {
  return (
    <button className="tk-mono" style={{
      padding: '4px 10px', height: 24, border: `1px solid ${active ? TK.ink : TK.rule2}`,
      background: active ? TK.ink : 'transparent', color: active ? TK.paper : TK.ink2,
      borderRadius: 2, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em',
      display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer',
    }}>
      {tone && <span className="tk-dot" style={{ background: tone, opacity: active ? 1 : 0.9 }} />}
      {children}
      {count != null && (
        <span style={{ color: active ? TK.paper3 : TK.ink3, fontWeight: 500 }}>{count}</span>
      )}
    </button>
  );
}

function ProposedBlotter() {
  return (
    <div className="tk" style={{ width: 1920, height: 1180, background: TK.paper, position: 'relative', overflow: 'hidden' }}>
      {/* Chrome bar */}
      <div style={{ height: 44, background: TK.panel, color: TK.panelInk, display: 'flex', alignItems: 'center', padding: '0 16px', gap: 18 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ width: 22, height: 22, background: TK.paper, color: TK.panel, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: TK.serif, fontWeight: 700, fontSize: 14 }}>T</div>
          <div style={{ fontFamily: TK.serif, fontSize: 15, fontWeight: 600 }}>Tokka Labs</div>
          <span style={{ color: TK.panelInk2, fontSize: 11, letterSpacing: '0.08em' }}>TRADE MGMT</span>
        </div>
        <div style={{ flex: 1 }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'rgba(255,255,255,0.06)', padding: '4px 10px', borderRadius: 3, fontSize: 11 }}>
          <span style={{ color: TK.panelInk2 }}>⌕</span>
          <span style={{ color: TK.panelInk2 }}>Search deals, counterparties, refs…</span>
          <span style={{ flex: 1, minWidth: 280 }} />
          <span className="tk-kbd" style={{ background: 'rgba(255,255,255,0.08)', borderColor: 'rgba(255,255,255,0.15)', color: TK.panelInk }}>⌘K</span>
        </div>
        <div style={{ flex: 1 }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, fontSize: 11, color: TK.panelInk2 }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span className="tk-dot" style={{ background: TK.buy }} /> services up
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span className="tk-dot" style={{ background: TK.confirmed }} /> 3 ws feeds
          </span>
          <span>2026-05-27 · 02:48:56 UTC</span>
          <div style={{ width: 24, height: 24, background: TK.paper, color: TK.panel, fontSize: 11, fontWeight: 600, display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 2 }}>DP</div>
        </div>
      </div>

      {/* Body */}
      <div style={{ display: 'flex', height: 1136 }}>
        {/* Sidebar */}
        <div style={{ width: 192, background: TK.paper, borderRight: `1px solid ${TK.rule}`, padding: '14px 0' }}>
          <div style={{ padding: '0 14px', marginBottom: 12 }}>
            <button className="tk-btn tk-btn-primary" style={{ width: '100%', padding: '8px 10px', fontSize: 11, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span>+ NEW DEAL</span>
              <span className="tk-kbd" style={{ background: 'rgba(255,255,255,0.1)', borderColor: 'rgba(255,255,255,0.2)', color: TK.paper }}>B</span>
            </button>
          </div>
          <div className="tk-label" style={{ padding: '8px 14px 4px' }}>Books</div>
          {[
            ['Deal Enquiry', true, 487],
            ['Loan Enquiry', false, 24],
            ['Pending Bookings', false, 6, TK.pending],
            ['Approvals', false, 2, TK.warn],
          ].map(([n, a, c, dot], i) => (
            <div key={i} style={{
              padding: '7px 14px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              background: a ? TK.paper2 : 'transparent',
              borderLeft: a ? `2px solid ${TK.ink}` : '2px solid transparent',
              fontWeight: a ? 600 : 400,
              fontSize: 12, cursor: 'pointer',
            }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {dot && <span className="tk-dot" style={{ background: dot }} />}
                {n}
              </span>
              <span className="tk-mono" style={{ color: TK.ink3, fontSize: 10 }}>{c}</span>
            </div>
          ))}
          <div className="tk-label" style={{ padding: '14px 14px 4px' }}>Reports</div>
          {['Position', 'P&L', 'Settlement', 'Counterparty Limits', 'Reconciliation'].map((n, i) => (
            <div key={i} style={{ padding: '7px 14px', fontSize: 12, cursor: 'pointer', color: TK.ink2 }}>{n}</div>
          ))}
          <div className="tk-label" style={{ padding: '14px 14px 4px' }}>Admin</div>
          {['Users', 'Portfolios', 'Counterparties', 'API Tokens'].map((n, i) => (
            <div key={i} style={{ padding: '7px 14px', fontSize: 12, cursor: 'pointer', color: TK.ink2 }}>{n}</div>
          ))}
        </div>

        {/* Main */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          {/* Page header */}
          <div style={{ padding: '14px 24px 10px', display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
            <div>
              <div className="tk-serif" style={{ fontSize: 26, fontWeight: 600, letterSpacing: '-0.01em' }}>Deal Enquiry</div>
              <div className="tk-mono" style={{ fontSize: 11, color: TK.ink3, marginTop: 2 }}>
                487 deals · 18 visible · last sync 02:48:53 UTC
              </div>
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <button className="tk-btn">+ Date Filter</button>
              <button className="tk-btn">Save View</button>
              <button className="tk-btn">↓ CSV</button>
              <button className="tk-btn">↓ Trade Bookings</button>
              <button className="tk-btn tk-btn-primary">+ New Deal</button>
            </div>
          </div>

          {/* Saved views tabs */}
          <div style={{ padding: '0 24px', display: 'flex', alignItems: 'center', gap: 0, borderBottom: `1px solid ${TK.rule}` }}>
            {[
              ['All open', true, 31],
              ['My pending', false, 4],
              ['Awaiting approval', false, 2],
              ['Due today', false, 7],
              ['Internal transfers', false, 12],
              ['Loans · active', false, 5],
              ['Cancelled · 30d', false, 9],
              ['+', false],
            ].map(([n, a, c], i) => (
              <div key={i} style={{
                padding: '8px 14px', fontSize: 12, cursor: 'pointer',
                borderBottom: a ? `2px solid ${TK.ink}` : '2px solid transparent',
                color: a ? TK.ink : TK.ink2, fontWeight: a ? 600 : 500,
                display: 'flex', alignItems: 'center', gap: 6,
                marginBottom: -1,
              }}>
                {n}
                {c != null && (
                  <span className="tk-mono" style={{
                    fontSize: 10, padding: '1px 5px', background: a ? TK.ink : TK.paper2,
                    color: a ? TK.paper : TK.ink3, borderRadius: 2,
                  }}>{c}</span>
                )}
              </div>
            ))}
          </div>

          {/* KPI strip */}
          <div style={{ padding: '12px 24px', display: 'flex', gap: 0, borderBottom: `1px solid ${TK.rule}`, background: TK.paper }}>
            <Stat label="Notional · open"  value="$4.21M" sub="▲ 1.2% wow"      tone={TK.confirmed} />
            <Stat label="Pending bookings" value="6"      sub="oldest 04m"       tone={TK.pending} />
            <Stat label="Due today"        value="7"      sub="$298K"           tone={TK.warn} />
            <Stat label="Approvals queued" value="2"      sub="awaiting checker" tone={TK.sell} />
            <Stat label="Settled · today"  value="14"     sub="$2.97M"          tone={TK.buy} />
            <Stat label="Cancelled · 30d"  value="9"      sub="3.0% rate"       tone={TK.rule2} />
            <div style={{ flex: 1 }} />
            <div style={{ alignSelf: 'center', display: 'flex', gap: 6 }}>
              <Spark data={[3,4,3,5,4,6,5,7,6,8,7,9,8,10,9]} w={120} h={32} color={TK.confirmed} />
              <div className="tk-mono" style={{ fontSize: 10, color: TK.ink3, alignSelf: 'flex-end' }}>volume · 7d</div>
            </div>
          </div>

          {/* Filter chip rows */}
          <div style={{ padding: '10px 24px', display: 'flex', flexDirection: 'column', gap: 8, borderBottom: `1px solid ${TK.rule}` }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span className="tk-label" style={{ width: 64 }}>Status</span>
              <Chip count={31}>All</Chip>
              <Chip tone={TK.pending}   count={6}>Pending</Chip>
              <Chip tone={TK.confirmed} count={4} active>Confirmed</Chip>
              <Chip tone={TK.processed} count={8} active>Processed</Chip>
              <Chip tone={TK.settled}   count={14}>Settled</Chip>
              <Chip tone={TK.cancelled} count={9}>Cancelled</Chip>
              <span className="tk-vrule" style={{ height: 18, margin: '0 4px' }} />
              <span className="tk-label" style={{ width: 64 }}>Type</span>
              <Chip active>Cashflow</Chip>
              <Chip>Spot</Chip>
              <Chip>Futures</Chip>
              <Chip>Loan</Chip>
              <Chip>Other</Chip>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span className="tk-label" style={{ width: 64 }}>Portfolio</span>
              <Chip>8000 · PMM</Chip>
              <Chip>8001 · CLOB</Chip>
              <Chip>8888 · Treasury</Chip>
              <span className="tk-vrule" style={{ height: 18, margin: '0 4px' }} />
              <span className="tk-label" style={{ width: 60 }}>Asset</span>
              <Chip>BTC</Chip>
              <Chip>ETH</Chip>
              <Chip>USDC</Chip>
              <Chip>USDT</Chip>
              <span className="tk-vrule" style={{ height: 18, margin: '0 4px' }} />
              <span className="tk-label" style={{ width: 60 }}>Venue</span>
              <Chip>CEX</Chip>
              <Chip>DEX</Chip>
              <Chip>OTC</Chip>
              <Chip>Internal</Chip>
              <div style={{ flex: 1 }} />
              <button className="tk-btn" style={{ fontSize: 10, padding: '4px 8px' }}>× clear all</button>
            </div>
          </div>

          {/* Table */}
          <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <div className="tk-mono" style={{
              display: 'grid',
              gridTemplateColumns: '34px 92px 132px 80px 56px 84px 200px 168px 60px 96px 88px 144px 102px 92px 28px',
              fontSize: 10, color: TK.ink3, textTransform: 'uppercase', letterSpacing: '0.05em',
              padding: '8px 24px', borderBottom: `1px solid ${TK.rule2}`, background: TK.paper2,
              alignItems: 'center', gap: 0,
            }}>
              <span><input type="checkbox" style={{ accentColor: TK.ink }} /></span>
              <span>Updated</span>
              <span>Ref</span>
              <span>Type</span>
              <span>Dir</span>
              <span>Ptf</span>
              <span>Portfolio name</span>
              <span>Counterparty</span>
              <span>Asset</span>
              <span style={{ textAlign: 'right' }}>Amount</span>
              <span>Venue</span>
              <span>Tag</span>
              <span style={{ textAlign: 'right' }}>Notional</span>
              <span>Status</span>
              <span></span>
            </div>

            <div style={{ overflow: 'auto', flex: 1 }}>
              {DEALS.map((d, i) => (
                <div key={d.ref} className={`tk-tr tk-mono ${i === 2 ? 'selected' : ''}`} style={{
                  display: 'grid',
                  gridTemplateColumns: '34px 92px 132px 80px 56px 84px 200px 168px 60px 96px 88px 144px 102px 92px 28px',
                  fontSize: 12, padding: '6px 24px',
                  borderBottom: `1px solid ${TK.rule}`,
                  alignItems: 'center',
                  background: i % 2 === 1 && i !== 2 ? 'rgba(0,0,0,0.015)' : 'transparent',
                  minHeight: 30,
                }}>
                  <span><input type="checkbox" style={{ accentColor: TK.ink }} defaultChecked={i===2} /></span>
                  <span style={{ color: TK.ink2, fontSize: 11 }}>
                    {d.date.slice(5)}<br />
                    <span style={{ color: TK.ink3, fontSize: 10 }}>{d.t}</span>
                  </span>
                  <span>
                    <span className="tk-link">{d.ref}</span>
                    {d.link && (
                      <div className="tk-mono" style={{ fontSize: 10, color: TK.ink3 }}>↳ {d.link}</div>
                    )}
                  </span>
                  <span style={{ color: TK.ink2, fontSize: 11 }}>{d.type}</span>
                  <span><DirGlyph d={d.dir} /></span>
                  <span style={{ color: TK.ink2 }}>{d.ptf}</span>
                  <span style={{ color: TK.ink, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', paddingRight: 8 }}>
                    {d.name}
                  </span>
                  <span style={{ color: TK.ink, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', paddingRight: 8 }}>
                    {d.cp}
                  </span>
                  <span style={{ fontWeight: 600 }}>{d.base}</span>
                  <span className="tk-num" style={{ textAlign: 'right', paddingRight: 16, fontWeight: 500 }}>{d.amt}</span>
                  <span style={{ color: TK.ink2, fontSize: 11 }}>{d.venue}</span>
                  <span style={{ color: TK.ink2, fontSize: 11 }}>{d.tag}</span>
                  <span className="tk-num" style={{ textAlign: 'right', paddingRight: 12, color: TK.ink2 }}>{d.notional}</span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <StatusPillFor s={d.status} />
                  </span>
                  <span style={{ color: TK.ink3, opacity: 0.5 }}>⋯</span>
                </div>
              ))}
            </div>

            {/* Footer aggregations */}
            <div className="tk-mono" style={{
              padding: '10px 24px', borderTop: `2px solid ${TK.ink}`,
              background: TK.paper2, display: 'flex', alignItems: 'center', gap: 24, fontSize: 11,
            }}>
              <span style={{ color: TK.ink3 }}>SELECTION · 1 row</span>
              <span className="tk-vrule" style={{ height: 16 }} />
              <span><span style={{ color: TK.ink3 }}>Σ amount </span><span className="tk-num" style={{ fontWeight: 600 }}>746,512.6731</span></span>
              <span><span style={{ color: TK.ink3 }}>Σ notional </span><span className="tk-num" style={{ fontWeight: 600 }}>$5,932,418.93 USD</span></span>
              <span><span style={{ color: TK.ink3 }}>by status </span>
                <Pill tone="pending">1</Pill>{' '}
                <Pill tone="confirmed">2</Pill>{' '}
                <Pill tone="processed">2</Pill>{' '}
                <Pill tone="settled">11</Pill>{' '}
                <Pill tone="cancelled">2</Pill>
              </span>
              <div style={{ flex: 1 }} />
              <span style={{ color: TK.ink3 }}>Bulk:</span>
              <button className="tk-btn" style={{ padding: '4px 10px' }}>Approve · 1</button>
              <button className="tk-btn" style={{ padding: '4px 10px' }}>Cancel</button>
              <button className="tk-btn" style={{ padding: '4px 10px' }}>Export</button>
              <span className="tk-vrule" style={{ height: 16 }} />
              <span className="tk-label">Keys</span>
              <span><span className="tk-kbd">B</span> book</span>
              <span><span className="tk-kbd">A</span> approve</span>
              <span><span className="tk-kbd">/</span> search</span>
              <span><span className="tk-kbd">J</span> <span className="tk-kbd">K</span> nav</span>
            </div>
          </div>
        </div>
      </div>

      {/* Annotation callouts */}
      <Note x={1260} y={220} w={340} side="left">
        <b>1. Saved views as tabs.</b> Operators live in a few queries — "my pending today",
        "due today", "awaiting approval". Tabs let them context-switch in one click.
      </Note>
      <Note x={1380} y={320} w={340} side="left">
        <b>2. KPI strip = footer for the eye.</b> Notional open, oldest pending age,
        due-today count. Aggregations belong at the top OR bottom, not nowhere.
      </Note>
      <Note x={32} y={510} w={300} side="right">
        <b>3. Chip-row filters &gt; dropdown filters.</b> Multi-axis filtering in
        one glance. Each chip shows count — operators see at a glance whether
        a filter has anything in it.
      </Note>
      <Note x={1660} y={500} w={250} side="left">
        <b>4. Structured columns.</b> Direction, asset, venue, tag — each as its
        own column with consistent formatting. Notional in a base currency.
      </Note>
      <Note x={32} y={830} w={280} side="right">
        <b>5. Row link affordance.</b> Linked deals shown inline with ↳.
        Click peeks the other side of the trade.
      </Note>
      <Note x={1500} y={1080} w={300} side="left">
        <b>6. Selection footer.</b> Multi-select rows → bulk approve / cancel /
        export. Σ amount and Σ notional update live. Status histogram at a glance.
      </Note>
    </div>
  );
}

Object.assign(window, { ProposedBlotter });
