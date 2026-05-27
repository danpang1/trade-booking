import React, { useEffect, useMemo, useState } from "react";
import { Check, X, ExternalLink, RefreshCw } from "lucide-react";
import { listDrafts, approveDraft, rejectDraft } from "../auth/api.js";

// Token-backed palette — every colour resolves from src/tokens.css so the
// pending inbox shares the same paper / ink / status surface as the rest
// of the app.
const BB = {
  bg:         "var(--paper)",
  panel:      "var(--paper-2)",
  panelHead:  "var(--paper-3)",
  border:     "var(--rule-2)",
  borderSoft: "var(--rule)",
  fg:         "var(--ink)",
  dim:        "var(--ink-3)",
  faint:      "var(--ink-4)",
  accent:     "var(--signal-link)",
  red:        "var(--signal-sell)",
  green:      "var(--signal-buy)",
};

function fmtDate(iso) {
  if (!iso) return "—";
  return iso.slice(0, 19).replace("T", " ");
}

// Coarse "Nm ago" / "Hh Mm ago" for the design's "submitted 00:04 ago".
function timeAgo(iso) {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const ms = Date.now() - t;
  if (ms < 0) return "just now";
  const mins = Math.floor(ms / 60000);
  if (mins < 1) return "<1m";
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ${mins % 60}m`;
  const days = Math.floor(hrs / 24);
  return `${days}d`;
}

function summarize(payload) {
  // One-line cashflow summary used in the card body and the
  // "Recently decided" compact grid. Defensive about missing fields.
  if (!payload || typeof payload !== "object") return "(empty)";
  const isIpf = payload.cashflow_type === "INTER PTF FUNDING";
  const cptyLabel = isIpf && payload.counterparty
    ? `ptf ${payload.counterparty}`
    : payload.counterparty;
  return [
    payload.cashflow_type,
    payload.portfolio_id ? `ptf ${payload.portfolio_id}` : null,
    payload.direction,
    payload.amount,
    payload.asset,
    cptyLabel,
    payload.network,
  ].filter(Boolean).join(" · ");
}

// Button presets — STYLE_GUIDE §6.3: mono 11px, 3px radius, hairline border.
const primaryBtn = { display: "inline-flex", alignItems: "center", gap: 6, background: "var(--panel)", color: "var(--panel-ink)", border: "1px solid var(--panel)", padding: "6px 10px", fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.05em", textTransform: "uppercase", cursor: "pointer", borderRadius: 3 };
const ghostBtn   = { display: "inline-flex", alignItems: "center", gap: 6, background: "var(--paper)", color: "var(--ink)", border: "1px solid var(--rule-2)", padding: "6px 10px", fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.05em", textTransform: "uppercase", cursor: "pointer", borderRadius: 3 };
const dangerBtn  = { display: "inline-flex", alignItems: "center", gap: 6, background: "var(--paper)", color: "var(--signal-sell)", border: "1px solid var(--signal-sell)", padding: "6px 10px", fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.05em", textTransform: "uppercase", cursor: "pointer", borderRadius: 3 };

// "Drafts created by makers · awaiting approval before settlement"-style
// label used above each section. Mono 10px uppercase ink-3.
const sectionLabel = {
  display: "block", fontFamily: "var(--font-mono)",
  fontSize: 10, color: "var(--ink-3)",
  textTransform: "uppercase", letterSpacing: "0.06em",
  fontWeight: 500, marginBottom: 8,
};

// Status-pill / signal-pill: mono 10 uppercase 600 weight,
// foreground colour + matching bg + matching border. Used for cashflow
// type, direction, decision badges.
function Pill({ tone, children }) {
  const palettes = {
    pending:   { bg: "var(--status-pending-bg)",   fg: "var(--status-pending)"   },
    confirmed: { bg: "var(--status-confirmed-bg)", fg: "var(--status-confirmed)" },
    processed: { bg: "var(--status-processed-bg)", fg: "var(--status-processed)" },
    settled:   { bg: "var(--status-settled-bg)",   fg: "var(--status-settled)"   },
    cancelled: { bg: "var(--status-cancelled-bg)", fg: "var(--status-cancelled)" },
    buy:       { bg: "var(--signal-buy-bg)",       fg: "var(--signal-buy)"       },
    sell:      { bg: "var(--signal-sell-bg)",      fg: "var(--signal-sell)"      },
    warn:      { bg: "var(--signal-warn-bg)",      fg: "var(--signal-warn)"      },
    muted:     { bg: "var(--paper-2)",             fg: "var(--ink-3)"            },
  };
  const p = palettes[tone] || palettes.muted;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center",
      padding: "2px 6px", borderRadius: 2, lineHeight: 1.2,
      background: p.bg, color: p.fg, border: `1px solid ${p.fg}`,
      fontFamily: "var(--font-mono)",
      fontSize: 10, fontWeight: 600,
      letterSpacing: "0.06em", textTransform: "uppercase",
    }}>{children}</span>
  );
}

// Inline kbd chip (matches STYLE_GUIDE §6.5).
function Kbd({ children, on = false }) {
  return (
    <span style={{
      fontFamily: "var(--font-mono)", fontSize: 10,
      padding: "1px 5px", borderRadius: 3,
      border: `1px solid ${on ? "rgba(255,255,255,0.25)" : "var(--rule-2)"}`,
      borderBottomWidth: 2,
      background: on ? "rgba(255,255,255,0.15)" : "var(--paper)",
      color: on ? "var(--panel-ink)" : "var(--ink-2)",
    }}>{children}</span>
  );
}

// Pick the cashflow-type pill tone — for "PAYMENT-ish" outflows we want
// the design's "sell" tone (red); inflows → "buy" (green). Anything
// else stays muted.
function directionTone(direction) {
  if (direction === "OUTGOING" || direction === "SHORT" || direction === "PAID") return "sell";
  if (direction === "INCOMING" || direction === "LONG" || direction === "RECEIVED") return "buy";
  return "muted";
}

export default function PendingDrafts({ onClose, onOpenDraft, onChanged }) {
  const [rows, setRows]       = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState("");
  const [rowError, setRowError] = useState({});  // {id: "msg"}
  const [selected, setSelected] = useState(() => new Set());  // pending draft ids
  const [bulkBusy, setBulkBusy] = useState(false);
  const [activeTab, setActiveTab] = useState("PENDING"); // PENDING | APPROVED | REJECTED

  async function load() {
    setLoading(true);
    const { status, body } = await listDrafts();
    if (status === 200 && body?.ok) {
      setRows(body.drafts || []);
      setError("");
      setRowError({});
      // Drop selection entries whose drafts are no longer PENDING_REVIEW
      // (e.g. just approved/rejected). Avoid stale highlights on rerender.
      const pendingIds = new Set(
        (body.drafts || []).filter((d) => d.status === "PENDING_REVIEW").map((d) => d.id)
      );
      setSelected((prev) => {
        const next = new Set();
        for (const id of prev) if (pendingIds.has(id)) next.add(id);
        return next;
      });
      // Tell the parent (sidebar badge) to refresh — saves the badge
      // from waiting up to 60s for its next poll after every action.
      onChanged?.();
    } else {
      setError(body?.error || `HTTP ${status}`);
    }
    setLoading(false);
  }

  function toggleSelected(id) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectGroup(list) {
    const ids = list.map((d) => d.id);
    const allOn = ids.every((id) => selected.has(id));
    setSelected((prev) => {
      const next = new Set(prev);
      if (allOn) ids.forEach((id) => next.delete(id));
      else ids.forEach((id) => next.add(id));
      return next;
    });
  }

  async function onBulkApprove() {
    const ids = Array.from(selected);
    if (ids.length === 0) return;
    if (!confirm(`Approve ${ids.length} draft${ids.length > 1 ? "s" : ""}? Each will insert into trades_cashflow.`)) return;
    setBulkBusy(true);
    for (const id of ids) {
      const { status, body } = await approveDraft(id);
      if (status !== 200 || !body?.ok) {
        setRowError((r) => ({ ...r, [id]: body?.error || `Approve failed (${status})` }));
      }
    }
    setBulkBusy(false);
    await load();
  }

  async function onBulkReject() {
    const ids = Array.from(selected);
    if (ids.length === 0) return;
    const reason = prompt(`Reject ${ids.length} draft${ids.length > 1 ? "s" : ""} — reason (optional, applied to all):`) ?? null;
    if (!confirm(`Reject ${ids.length} draft${ids.length > 1 ? "s" : ""}?`)) return;
    setBulkBusy(true);
    for (const id of ids) {
      const { status, body } = await rejectDraft(id, reason);
      if (status !== 200 || !body?.ok) {
        setRowError((r) => ({ ...r, [id]: body?.error || `Reject failed (${status})` }));
      }
    }
    setBulkBusy(false);
    await load();
  }

  useEffect(() => { load(); }, []);

  // A/R keyboard shortcuts when on the PENDING tab with at least one card
  // selected — matches STYLE_GUIDE §Interactions.
  useEffect(() => {
    if (activeTab !== "PENDING") return;
    const onKey = (e) => {
      if (selected.size === 0) return;
      // Ignore when typing in an input/textarea.
      const tag = (e.target?.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select") return;
      if (e.key === "a" || e.key === "A") { e.preventDefault(); onBulkApprove(); }
      else if (e.key === "r" || e.key === "R") { e.preventDefault(); onBulkReject(); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [activeTab, selected]);

  const { pending, approved, rejected } = useMemo(() => {
    const p = [], a = [], r = [];
    for (const d of rows) {
      if (d.status === "PENDING_REVIEW") p.push(d);
      else if (d.status === "APPROVED") a.push(d);
      else if (d.status === "REJECTED") r.push(d);
    }
    return { pending: p, approved: a, rejected: r };
  }, [rows]);

  // Recently-decided feed on the PENDING tab — merges approved + rejected
  // and shows the most recent 10 so makers can see the queue's recent
  // throughput without leaving the page.
  const recentlyDecided = useMemo(() => {
    const merged = [
      ...approved.map((d) => ({ ...d, _decision: "approved" })),
      ...rejected.map((d) => ({ ...d, _decision: "rejected" })),
    ];
    merged.sort((a, b) => {
      const ta = (a.approved_at || a.rejected_at || a.created_at || "");
      const tb = (b.approved_at || b.rejected_at || b.created_at || "");
      return tb.localeCompare(ta);
    });
    return merged.slice(0, 10);
  }, [approved, rejected]);

  // Group pending into batches (one group per batch_id, plus a singles group).
  const pendingGroups = useMemo(() => {
    const byBatch = new Map();
    const singles = [];
    for (const d of pending) {
      if (d.batch_id) {
        if (!byBatch.has(d.batch_id)) byBatch.set(d.batch_id, []);
        byBatch.get(d.batch_id).push(d);
      } else {
        singles.push(d);
      }
    }
    const groups = [];
    for (const [batchId, list] of byBatch.entries()) {
      groups.push({ batchId, list, isSingle: false });
    }
    for (const d of singles) {
      groups.push({ batchId: null, list: [d], isSingle: true });
    }
    // Newest groups first (by first row's created_at).
    groups.sort((g1, g2) => g2.list[0].created_at.localeCompare(g1.list[0].created_at));
    return groups;
  }, [pending]);

  async function onApprove(d) {
    if (!confirm(`Approve draft #${d.id}? This inserts into trades_cashflow.`)) return;
    const { status, body } = await approveDraft(d.id);
    if (status !== 200 || !body?.ok) {
      setRowError((r) => ({ ...r, [d.id]: body?.error || `Approve failed (${status})` }));
      return;
    }
    await load();
  }

  async function onReject(d) {
    const reason = prompt(`Reject draft #${d.id} — reason (optional):`) ?? null;
    const { status, body } = await rejectDraft(d.id, reason);
    if (status !== 200 || !body?.ok) {
      setRowError((r) => ({ ...r, [d.id]: body?.error || `Reject failed (${status})` }));
      return;
    }
    await load();
  }

  async function onApproveAll(list) {
    if (!confirm(`Approve all ${list.length} pending drafts in this batch?`)) return;
    for (const d of list) {
      const { status, body } = await approveDraft(d.id);
      if (status !== 200 || !body?.ok) {
        setRowError((r) => ({ ...r, [d.id]: body?.error || `Approve failed (${status})` }));
      }
    }
    await load();
  }

  function openInForm(d) {
    if (onOpenDraft) {
      onOpenDraft(d.id);
    } else {
      window.location.href = `/?draft=${d.id}`;
    }
  }

  // ────────────────────────────────────────────────────────────────────
  // Card-style pending row (STYLE_GUIDE §"Pending Bookings"):
  //   paper-2 bg, 1px rule-2 border, 3px confirmed left border, 3px radius
  //   ref + cashflow-type pill + direction pill on one row · "submitted
  //   Xm ago by Y" on the right · single-line summary · action row.
  // ────────────────────────────────────────────────────────────────────
  function PendingCard({ d }) {
    const p = d.payload || {};
    const isSelected = selected.has(d.id);
    return (
      <div style={{
        background: "var(--paper-2)",
        border: "1px solid var(--rule-2)",
        borderLeft: "3px solid var(--status-confirmed)",
        padding: 14,
        marginBottom: 10,
        borderRadius: 3,
        outline: isSelected ? "2px solid var(--ink)" : "none",
        outlineOffset: -1,
      }}>
        {/* Top row: select + ref + type/direction pills · submitted-time */}
        <div style={{
          display: "flex", alignItems: "baseline",
          justifyContent: "space-between", gap: 12, marginBottom: 8,
        }}>
          <div style={{
            display: "flex", alignItems: "baseline", gap: 10,
            flexWrap: "wrap",
          }}>
            <input
              type="checkbox"
              checked={isSelected}
              onChange={() => toggleSelected(d.id)}
              style={{ cursor: "pointer", margin: 0, alignSelf: "center" }}
              aria-label={`Select draft ${d.id}`}
            />
            <span
              onClick={() => openInForm(d)}
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 13, fontWeight: 600,
                color: "var(--signal-link)",
                borderBottom: "1px dotted var(--signal-link)",
                cursor: "pointer",
              }}
              title="Open in TradeBookingForm"
            >
              #{d.id}
            </span>
            {p.cashflow_type && <Pill tone="muted">{p.cashflow_type}</Pill>}
            {p.direction && <Pill tone={directionTone(p.direction)}>{p.direction}</Pill>}
          </div>
          <div style={{
            fontFamily: "var(--font-mono)", fontSize: 11,
            color: "var(--ink-3)", whiteSpace: "nowrap",
          }}>
            submitted <b style={{ color: "var(--ink)" }}>{timeAgo(d.created_at)}</b> ago
            {d.created_by && (
              <> by <b style={{ color: "var(--ink)" }}>{d.created_by}</b></>
            )}
          </div>
        </div>

        {/* Single-line summary, mono 13 */}
        <div style={{
          fontFamily: "var(--font-mono)", fontSize: 13,
          color: "var(--ink)", marginBottom: 6,
        }}>
          {summarize(p)}
        </div>

        {/* Sub-line — counterparty / account / portfolio name in mono 11 */}
        <div style={{
          fontFamily: "var(--font-mono)", fontSize: 11,
          color: "var(--ink-3)", marginBottom: 12,
        }}>
          {p.counterparty && (
            <>counterparty <b style={{ color: "var(--ink-2)" }}>{p.counterparty}</b>{" "}</>
          )}
          {p.account && (
            <>· account <b style={{ color: "var(--ink-2)" }}>{p.account}</b>{" "}</>
          )}
          {p.portfolio_name && (
            <>· portfolio <b style={{ color: "var(--ink-2)" }}>{p.portfolio_name}</b></>
          )}
        </div>

        {/* Action row */}
        <div style={{ display: "flex", gap: 6 }}>
          <button
            style={{ ...primaryBtn, flex: 1, justifyContent: "center" }}
            onClick={() => onApprove(d)}
          >
            <Check size={12} /> Approve <Kbd on>A</Kbd>
          </button>
          <button
            style={{ ...dangerBtn, flex: 1, justifyContent: "center" }}
            onClick={() => onReject(d)}
          >
            <X size={12} /> Reject <Kbd>R</Kbd>
          </button>
          <button style={ghostBtn} onClick={() => openInForm(d)}>
            <ExternalLink size={12} /> Open draft
          </button>
        </div>

        {rowError[d.id] && (
          <div style={{
            color: "var(--signal-sell)", fontSize: 10, marginTop: 6,
            fontFamily: "var(--font-mono)",
          }}>
            {rowError[d.id]}
          </div>
        )}
      </div>
    );
  }

  // ────────────────────────────────────────────────────────────────────
  // Compact decided-row grid — STYLE_GUIDE §"Recently decided".
  // Columns: ref · decision pill · type · time · "by user · note".
  // Used on the PENDING tab's "Recently decided" feed and on the
  // APPROVED / REJECTED tabs as the full list.
  // ────────────────────────────────────────────────────────────────────
  function DecidedGrid({ items, showNoteCol = true }) {
    if (items.length === 0) {
      return (
        <div style={{ fontSize: 11, color: "var(--ink-3)", padding: "12px 0" }}>
          No items.
        </div>
      );
    }
    return (
      <div style={{
        border: "1px solid var(--rule)", borderRadius: 3, overflow: "hidden",
      }}>
        {items.map((d, i) => {
          const dec = d._decision || (d.status === "APPROVED" ? "approved" : "rejected");
          const time = fmtDate(d.approved_at || d.rejected_at || d.created_at);
          const by = d.approved_by || d.rejected_by || "—";
          const note = d.rejection_reason || (d.approved_deal_ref ? `→ ${d.approved_deal_ref}` : "");
          return (
            <div key={d.id} style={{
              display: "grid",
              gridTemplateColumns: showNoteCol
                ? "100px 100px 70px 140px 1fr"
                : "100px 100px 70px 140px",
              alignItems: "center",
              padding: "8px 12px",
              borderBottom: i < items.length - 1 ? "1px solid var(--rule)" : "none",
              background: i % 2 === 1 ? "rgba(0,0,0,0.015)" : "transparent",
              fontFamily: "var(--font-mono)", fontSize: 11,
              gap: 8,
            }}>
              <span
                onClick={() => openInForm(d)}
                style={{
                  color: "var(--signal-link)",
                  borderBottom: "1px dotted var(--signal-link)",
                  cursor: "pointer",
                  fontWeight: 600,
                }}
                title="Open draft"
              >#{d.id}</span>
              <span>
                <Pill tone={dec === "approved" ? "settled" : "cancelled"}>
                  {dec === "approved" ? "✓ approved" : "✕ rejected"}
                </Pill>
              </span>
              <span style={{ color: "var(--ink-3)" }}>
                {d.payload?.cashflow_type
                  ? d.payload.cashflow_type.split(" ")[0]
                  : "—"}
              </span>
              <span style={{ color: "var(--ink-3)", fontVariantNumeric: "tabular-nums" }}>
                {time}
              </span>
              {showNoteCol && (
                <span style={{ color: "var(--ink-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  by <b style={{ color: "var(--ink-2)" }}>{by}</b>
                  {note && <span> · "{note}"</span>}
                </span>
              )}
            </div>
          );
        })}
      </div>
    );
  }

  // Top-right segmented tab control (Pending N | Approved N | Rejected N).
  const tabs = [
    { key: "PENDING",  label: "Pending",  count: pending.length  },
    { key: "APPROVED", label: "Approved", count: approved.length },
    { key: "REJECTED", label: "Rejected", count: rejected.length },
  ];

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 30, overflow: "auto",
      background: BB.bg, color: BB.fg,
      fontFamily: "var(--font-mono)",
    }}>
      {/* ─── Header — serif title + tab control + subtitle + actions ─── */}
      <div style={{
        padding: "14px 24px 12px",
        borderBottom: `1px solid ${BB.borderSoft}`,
      }}>
        <div style={{
          display: "flex", alignItems: "baseline",
          justifyContent: "space-between", gap: 16,
        }}>
          <div style={{
            fontFamily: "var(--font-serif)",
            fontSize: 22, fontWeight: 600, letterSpacing: "-0.01em",
            color: "var(--ink)",
          }}>
            Pending Bookings
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {/* Segmented tab control */}
            <div style={{
              display: "flex", gap: 0,
              border: "1px solid var(--rule-2)", borderRadius: 3,
              overflow: "hidden",
            }}>
              {tabs.map((t, i) => {
                const isActive = activeTab === t.key;
                return (
                  <button
                    key={t.key}
                    onClick={() => setActiveTab(t.key)}
                    style={{
                      padding: "5px 12px",
                      fontFamily: "var(--font-mono)", fontSize: 11,
                      background: isActive ? "var(--ink)" : "transparent",
                      color: isActive ? "var(--paper)" : "var(--ink-2)",
                      border: "none",
                      borderRight: i < tabs.length - 1 ? "1px solid var(--rule-2)" : "none",
                      textTransform: "uppercase", letterSpacing: "0.05em",
                      cursor: "pointer", fontWeight: isActive ? 600 : 500,
                    }}
                  >
                    {t.label} {t.count}
                  </button>
                );
              })}
            </div>
            <button onClick={load} style={ghostBtn} title="Refresh">
              <RefreshCw size={14} />
            </button>
            <button onClick={onClose} style={ghostBtn} title="Close">
              <X size={14} />
            </button>
          </div>
        </div>
        <div style={{
          fontFamily: "var(--font-mono)", fontSize: 11,
          color: "var(--ink-3)", marginTop: 6,
        }}>
          Drafts created by makers · awaiting approval before settlement
        </div>
      </div>

      {error && (
        <div style={{
          padding: "10px 24px", color: "var(--signal-sell)",
          fontSize: 11, fontFamily: "var(--font-mono)",
        }}>
          {error}
        </div>
      )}

      {/* Sticky bulk-action bar — only shown on PENDING tab with selection */}
      {activeTab === "PENDING" && selected.size > 0 && (
        <div style={{
          position: "sticky", top: 0, zIndex: 5,
          background: "var(--paper-2)",
          borderBottom: "2px solid var(--ink)",
          padding: "10px 24px",
          display: "flex", alignItems: "center", justifyContent: "space-between",
          gap: 12,
        }}>
          <div style={{
            fontSize: 11, letterSpacing: "0.06em", color: "var(--ink-3)",
            textTransform: "uppercase",
          }}>
            {selected.size} selected
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              style={{ ...ghostBtn, opacity: bulkBusy ? 0.5 : 1 }}
              onClick={() => setSelected(new Set())}
              disabled={bulkBusy}
            >Clear</button>
            <button
              style={{ ...dangerBtn, opacity: bulkBusy ? 0.5 : 1 }}
              onClick={onBulkReject}
              disabled={bulkBusy}
            >
              <X size={12} /> Reject {selected.size} <Kbd>R</Kbd>
            </button>
            <button
              style={{ ...primaryBtn, opacity: bulkBusy ? 0.5 : 1 }}
              onClick={onBulkApprove}
              disabled={bulkBusy}
            >
              <Check size={12} /> Approve {selected.size} <Kbd on>A</Kbd>
            </button>
          </div>
        </div>
      )}

      <div style={{ padding: "16px 24px 32px" }}>
        {loading ? (
          <div style={{ color: BB.dim, fontSize: 11 }}>LOADING...</div>
        ) : activeTab === "PENDING" ? (
          <>
            <div style={sectionLabel}>Awaiting action · {pending.length}</div>
            {pending.length === 0 ? (
              <div style={{ fontSize: 11, color: "var(--ink-3)", padding: "8px 0 16px" }}>
                No pending drafts.
              </div>
            ) : (
              pendingGroups.map((g, gi) => (
                <div key={g.batchId || `single-${gi}`} style={{ marginBottom: 14 }}>
                  {/* Batch group bar — only shown for multi-trade batches */}
                  {!g.isSingle && (
                    <div style={{
                      display: "flex", justifyContent: "space-between",
                      alignItems: "center",
                      padding: "6px 12px", marginBottom: 8,
                      background: "var(--paper-2)",
                      border: "1px solid var(--rule)",
                      borderRadius: 3,
                      fontFamily: "var(--font-mono)", fontSize: 10,
                      color: "var(--ink-3)", letterSpacing: "0.06em",
                      textTransform: "uppercase",
                    }}>
                      <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <input
                          type="checkbox"
                          checked={g.list.every((d) => selected.has(d.id))}
                          ref={(el) => {
                            if (!el) return;
                            const some = g.list.some((d) => selected.has(d.id));
                            const all = g.list.every((d) => selected.has(d.id));
                            el.indeterminate = some && !all;
                          }}
                          onChange={() => toggleSelectGroup(g.list)}
                          style={{ cursor: "pointer", margin: 0 }}
                          aria-label="Select all in batch"
                        />
                        Batch {g.batchId.slice(0, 8)}… · {g.list.length} drafts · {fmtDate(g.list[0].created_at)}
                      </span>
                      <button
                        style={{ ...ghostBtn, padding: "3px 8px", fontSize: 10 }}
                        onClick={() => onApproveAll(g.list)}
                      >
                        Approve all {g.list.length}
                      </button>
                    </div>
                  )}
                  {g.list.map((d) => <PendingCard key={d.id} d={d} />)}
                </div>
              ))
            )}

            {recentlyDecided.length > 0 && (
              <>
                <div style={{ ...sectionLabel, marginTop: 24 }}>Recently decided</div>
                <DecidedGrid items={recentlyDecided} />
              </>
            )}
          </>
        ) : activeTab === "APPROVED" ? (
          <>
            <div style={sectionLabel}>Approved · {approved.length}</div>
            <DecidedGrid items={approved} />
          </>
        ) : (
          <>
            <div style={sectionLabel}>Rejected · {rejected.length}</div>
            <DecidedGrid items={rejected} />
          </>
        )}
      </div>
    </div>
  );
}
