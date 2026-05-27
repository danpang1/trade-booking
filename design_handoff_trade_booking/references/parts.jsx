// Reusable bits shared across the mock UIs.
// Status pill, dot, key-value, mini blotter row, etc.

const { TK } = window;

function Pill({ tone='ink', children, dot, outline }) {
  const map = {
    ink:       { bg: '#1b1815', fg: '#f1e8d3', bd: '#1b1815' },
    pending:   { bg: TK.pendingBg,   fg: TK.pending,   bd: TK.pending },
    confirmed: { bg: TK.confirmedBg, fg: TK.confirmed, bd: TK.confirmed },
    processed: { bg: TK.processedBg, fg: TK.processed, bd: TK.processed },
    settled:   { bg: TK.settledBg,   fg: TK.settled,   bd: TK.settled },
    cancelled: { bg: TK.cancelledBg, fg: TK.cancelled, bd: TK.cancelled },
    buy:       { bg: TK.buyBg,       fg: TK.buy,       bd: TK.buy },
    sell:      { bg: TK.sellBg,      fg: TK.sell,      bd: TK.sell },
    warn:      { bg: TK.warnBg,      fg: TK.warn,      bd: TK.warn },
    err:       { bg: TK.errBg,       fg: TK.err,       bd: TK.err },
    muted:     { bg: TK.paper2,      fg: TK.ink3,      bd: TK.rule2 },
  };
  const c = map[tone] || map.ink;
  return (
    <span className="tk-pill" style={{
      background: outline ? 'transparent' : c.bg,
      color: c.fg,
      borderColor: c.bd,
    }}>
      {dot && <span className="tk-dot" style={{ background: c.fg }} />}
      {children}
    </span>
  );
}

function KV({ k, v, mono=true, num=false, align='left', w }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: w }}>
      <div className="tk-label">{k}</div>
      <div className={`${mono ? 'tk-mono' : 'tk-serif'} ${num ? 'tk-num' : ''}`}
           style={{ fontSize: 13, color: TK.ink, textAlign: align, fontWeight: 500 }}>
        {v}
      </div>
    </div>
  );
}

// Stat tile for dashboards / footer aggregations
function Stat({ label, value, sub, tone, w=140 }) {
  return (
    <div style={{ minWidth: w, padding: '8px 12px', borderLeft: `3px solid ${tone || TK.rule2}` }}>
      <div className="tk-label">{label}</div>
      <div className="tk-mono tk-num" style={{ fontSize: 18, fontWeight: 600, color: TK.ink, marginTop: 2 }}>{value}</div>
      {sub && <div className="tk-mono" style={{ fontSize: 10, color: TK.ink3, marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

// Side icon column — small square icon buttons
function IconBtn({ children, active, title }) {
  return (
    <button className="tk-btn" title={title} style={{
      width: 28, height: 28, padding: 0, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      background: active ? TK.ink : 'transparent', color: active ? TK.paper : TK.ink2,
      borderColor: active ? TK.ink : 'transparent',
    }}>{children}</button>
  );
}

// Trend arrow
function Delta({ v, abs }) {
  const up = v >= 0;
  return (
    <span className="tk-num" style={{ color: up ? TK.buy : TK.sell, fontWeight: 600 }}>
      {up ? '▲' : '▼'} {abs ? Math.abs(v) : v}
    </span>
  );
}

// Sparkline (rough)
function Spark({ data, w=80, h=22, color=TK.ink2 }) {
  const min = Math.min(...data), max = Math.max(...data);
  const r = max - min || 1;
  const pts = data.map((d, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - ((d - min) / r) * h;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  return (
    <svg width={w} height={h} style={{ display: 'block' }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.25" />
    </svg>
  );
}

// Annotation callout that absolutely-positions over an artboard
function Note({ x, y, w=240, side='left', children }) {
  return (
    <div className={`anno ${side}`} style={{ left: x, top: y, width: w }}>
      {children}
    </div>
  );
}

// Section header within artboards
function ABHeader({ title, sub, right }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
      padding: '14px 18px 10px', borderBottom: `1px solid ${TK.rule}`,
    }}>
      <div>
        <div className="tk-serif" style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.01em' }}>{title}</div>
        {sub && <div className="tk-mono" style={{ fontSize: 11, color: TK.ink3, marginTop: 2 }}>{sub}</div>}
      </div>
      {right}
    </div>
  );
}

Object.assign(window, { Pill, KV, Stat, IconBtn, Delta, Spark, Note, ABHeader });
