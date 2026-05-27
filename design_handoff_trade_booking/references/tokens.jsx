// Shared visual tokens that match — and tighten — the Tokka aesthetic.
// Monospace + transitional serif, cream paper, ink black, status pastels.
// Exported globally for use across artboards.

const TK = {
  // Paper / surface — clean white with warm-grey supports
  paper:       '#ffffff',  // primary background
  paper2:      '#f6f5f2',  // row alt / sidebar bg
  paper3:      '#ecebe7',  // panel inset / KPI strip
  ink:         '#161513',  // primary text (warm black)
  ink2:        '#46423b',  // secondary
  ink3:        '#6e695f',  // tertiary / labels
  ink4:        '#a09a90',  // disabled / hint
  rule:        '#e6e3dd',  // hairline
  rule2:       '#c9c5bd',  // stronger hairline
  panel:       '#0d0c0a',  // chrome / sidebar / header
  panelInk:    '#ece8dc',
  panelInk2:   '#8a8678',

  // Semantic — keep within institutional palette
  buy:         '#1f6f4a',   // long / received / credit
  buyBg:       '#dff0e3',
  sell:        '#a83838',   // short / paid / debit
  sellBg:      '#f5dcd7',
  pending:     '#a37312',
  pendingBg:   '#f8ebcb',
  confirmed:   '#3a5fb0',
  confirmedBg: '#e2e9f6',
  processed:   '#2a7560',
  processedBg: '#dfeee7',
  settled:     '#1f6f4a',
  settledBg:   '#dff0e3',
  cancelled:   '#7a7363',
  cancelledBg: '#e6e2d6',
  warn:        '#a35c12',
  warnBg:      '#f8e5c8',
  err:         '#a83838',
  errBg:       '#f5dcd7',
  link:        '#365dbb',

  // Type
  mono:  '"JetBrains Mono", "IBM Plex Mono", ui-monospace, Menlo, monospace',
  serif: '"Source Serif 4", "IBM Plex Serif", "Spectral", Georgia, serif',
  sans:  '"Inter", system-ui, -apple-system, sans-serif',

  // Density
  rowH:    28,    // dense blotter row
  rowHmed: 34,
  pad:     12,
  radius:  3,     // institutional sharpness — no big rounded
  radiusSm:2,
};

// One-time font import
if (typeof document !== 'undefined' && !document.getElementById('tk-fonts')) {
  const link = document.createElement('link');
  link.id = 'tk-fonts';
  link.rel = 'stylesheet';
  link.href = 'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Source+Serif+4:opsz,wght@8..60,400;8..60,500;8..60,600;8..60,700&family=Inter:wght@400;500;600&display=swap';
  document.head.appendChild(link);
}

// One-time global CSS for the mock UIs
if (typeof document !== 'undefined' && !document.getElementById('tk-base')) {
  const s = document.createElement('style');
  s.id = 'tk-base';
  s.textContent = `
    .tk { font-family: ${TK.mono}; color: ${TK.ink}; background: ${TK.paper}; font-size: 12px; line-height: 1.35; }
    .tk, .tk * { box-sizing: border-box; }
    .tk-serif { font-family: ${TK.serif}; letter-spacing: -0.005em; }
    .tk-mono  { font-family: ${TK.mono}; }
    .tk-up    { text-transform: uppercase; letter-spacing: 0.04em; }
    .tk-label { font-family: ${TK.mono}; text-transform: uppercase; letter-spacing: 0.06em; font-size: 10px; color: ${TK.ink3}; font-weight: 500; }
    .tk-rule  { background: ${TK.rule}; height: 1px; width: 100%; }
    .tk-vrule { background: ${TK.rule}; width: 1px; align-self: stretch; }
    .tk-pill  { display:inline-flex; align-items:center; gap:4px; padding: 2px 6px; border-radius: 2px;
                font-family: ${TK.mono}; font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em;
                border: 1px solid transparent; line-height: 1.2; }
    .tk-dot   { width: 6px; height: 6px; border-radius: 50%; display: inline-block; }
    .tk-btn   { font-family: ${TK.mono}; font-size: 11px; padding: 6px 10px; border: 1px solid ${TK.rule2};
                background: ${TK.paper}; color: ${TK.ink}; cursor: pointer; text-transform: uppercase; letter-spacing: 0.05em;
                border-radius: ${TK.radius}px; }
    .tk-btn:hover { background: ${TK.paper2}; }
    .tk-btn-primary { background: ${TK.panel}; color: ${TK.panelInk}; border-color: ${TK.panel}; }
    .tk-btn-primary:hover { background: #232017; }
    .tk-input { font-family: ${TK.mono}; font-size: 12px; padding: 6px 8px; border: 1px solid ${TK.rule2};
                background: ${TK.paper}; color: ${TK.ink}; border-radius: ${TK.radius}px; width: 100%;
                outline: none; }
    .tk-input:focus { border-color: ${TK.ink2}; box-shadow: inset 0 0 0 1px ${TK.ink2}; }
    .tk-num { font-variant-numeric: tabular-nums; font-feature-settings: "tnum"; }
    .tk-tr:hover { background: ${TK.paper2}; }
    .tk-tr.selected { background: ${TK.paper3}; box-shadow: inset 3px 0 0 ${TK.ink}; }
    .tk-link { color: ${TK.link}; text-decoration: none; border-bottom: 1px dotted ${TK.link}; cursor: pointer; }
    .tk-kbd { font-family: ${TK.mono}; font-size: 10px; padding: 1px 5px; border: 1px solid ${TK.rule2};
              border-bottom-width: 2px; border-radius: 3px; background: ${TK.paper}; color: ${TK.ink2}; }
    /* anno callouts on artboards */
    .anno { position:absolute; font-family: ${TK.mono}; font-size: 11px; line-height: 1.4;
            background: #1b1815; color: #f1e8d3; padding: 8px 10px; border-radius: 3px;
            box-shadow: 0 6px 18px rgba(0,0,0,0.25); max-width: 260px; z-index: 10; }
    .anno b { color: #f5c97a; font-weight: 600; }
    .anno::before { content: ''; position: absolute; width:8px; height:8px; background:#1b1815; transform: rotate(45deg); }
    .anno.left::before { left: -3px; top: 14px; }
    .anno.right::before { right: -3px; top: 14px; }
    .anno.top::before { top: -3px; left: 14px; }
    .anno.bot::before { bottom: -3px; left: 14px; }
  `;
  document.head.appendChild(s);
}

window.TK = TK;
