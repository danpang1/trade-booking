import React, { useEffect, useMemo, useState } from "react";
import { Check, X, ExternalLink, RefreshCw } from "lucide-react";
import { listDrafts, approveDraft, rejectDraft } from "../auth/api.js";

// Altas editorial palette — mirrors TradeBookingForm.jsx BB tokens
// (bone canvas / chalk panels / hair borders / ink text / tokka blue accent).
const BB = {
  bg: "#ffffff",           // white canvas
  panel: "#f8f6f1",        // chalk (table body, group cards)
  panelHead: "#efece4",    // muted chalk (table header rows, group bar)
  border: "#d9d4c7",       // hair (primary divider)
  borderSoft: "#efece4",   // sub-divider (between rows)
  fg: "#0d0d0d",           // ink (primary text)
  dim: "#6a665c",          // slate (labels / muted text)
  faint: "#9a9488",        // helpers
  accent: "#1f63ea",       // tokka blue (primary CTA)
  accentDeep: "#1a4fbb",   // tokka blue deep (hover)
  red: "#b91c1c",          // red-700 (reject / errors)
  green: "#047857",        // emerald-700 (approve / booked refs)
};

function fmtDate(iso) {
  if (!iso) return "—";
  return iso.slice(0, 19).replace("T", " ");
}

function summarize(payload) {
  // Render a single cashflow row as one compact line.
  // Defensive about missing fields: drafts can be patched into any shape.
  if (!payload || typeof payload !== "object") return "(empty)";
  // For INTER PTF FUNDING the `counterparty` field holds the OTHER
  // portfolio's number (the picker swaps in TradeBookingForm.jsx). Label
  // it `ptf <n>` so readers don't mistake it for this row's portfolio_id.
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

const th = { padding: "8px 12px", textAlign: "left", color: BB.dim, fontSize: 10, letterSpacing: 1.5, textTransform: "uppercase", background: BB.panelHead, borderBottom: `1px solid ${BB.border}`, fontWeight: 500 };
const td = { padding: "8px 12px", borderBottom: `1px solid ${BB.borderSoft}`, fontSize: 12, color: BB.fg };
const primaryBtn = { display: "inline-flex", alignItems: "center", gap: 6, background: BB.accent, color: "#ffffff", border: `1px solid ${BB.accent}`, padding: "4px 10px", fontFamily: "inherit", fontSize: 11, letterSpacing: 1, cursor: "pointer", borderRadius: 0 };
const ghostBtn   = { display: "inline-flex", alignItems: "center", gap: 6, background: BB.bg, color: BB.fg, border: `1px solid ${BB.border}`, padding: "4px 10px", fontFamily: "inherit", fontSize: 11, letterSpacing: 1, cursor: "pointer", borderRadius: 0 };
const iconOK     = { display: "inline-flex", alignItems: "center", justifyContent: "center", background: BB.bg, color: BB.green, border: `1px solid ${BB.green}`, padding: 4, cursor: "pointer", borderRadius: 0 };
const iconNO     = { display: "inline-flex", alignItems: "center", justifyContent: "center", background: BB.bg, color: BB.red, border: `1px solid ${BB.red}`, padding: 4, cursor: "pointer", borderRadius: 0 };

export default function PendingDrafts({ onClose, onOpenDraft }) {
  const [rows, setRows]       = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState("");
  const [rowError, setRowError] = useState({});  // {id: "msg"}
  const [showApproved, setShowApproved] = useState(false);
  const [showRejected, setShowRejected] = useState(false);

  async function load() {
    setLoading(true);
    const { status, body } = await listDrafts();
    if (status === 200 && body?.ok) {
      setRows(body.drafts || []);
      setError("");
      setRowError({});
    } else {
      setError(body?.error || `HTTP ${status}`);
    }
    setLoading(false);
  }

  useEffect(() => { load(); }, []);

  const { pending, approved, rejected } = useMemo(() => {
    const p = [], a = [], r = [];
    for (const d of rows) {
      if (d.status === "PENDING_REVIEW") p.push(d);
      else if (d.status === "APPROVED") a.push(d);
      else if (d.status === "REJECTED") r.push(d);
    }
    return { pending: p, approved: a, rejected: r };
  }, [rows]);

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
    // Open the booking-form modal over this inbox via the parent's
    // onOpenDraft callback (lifts modal state into TradeBookingForm).
    // Fallback: deep-link via URL nav if no callback was wired.
    if (onOpenDraft) {
      onOpenDraft(d.id);
    } else {
      window.location.href = `/?draft=${d.id}`;
    }
  }

  function renderRow(d) {
    return (
      <tr key={d.id}>
        <td style={{ ...td, color: BB.dim }}>#{d.id}</td>
        <td style={td}>{summarize(d.payload)}</td>
        <td style={{ ...td, color: BB.dim }}>{fmtDate(d.created_at)}</td>
        <td style={{ ...td, color: d.approved_deal_ref ? BB.green : (d.rejected_at ? BB.red : BB.accent) }}>
          {d.approved_deal_ref || (d.rejected_at ? "REJECTED" : "PENDING")}
        </td>
        <td style={td}>
          {d.status === "PENDING_REVIEW" && (
            <div style={{ display: "flex", gap: 6 }}>
              <button style={ghostBtn} onClick={() => openInForm(d)} title="Open in TradeBookingForm">
                <ExternalLink size={12} /> FORM
              </button>
              <button style={iconOK} onClick={() => onApprove(d)} title="Approve">
                <Check size={12} />
              </button>
              <button style={iconNO} onClick={() => onReject(d)} title="Reject">
                <X size={12} />
              </button>
            </div>
          )}
          {rowError[d.id] && (
            <div style={{ color: BB.red, fontSize: 10, marginTop: 4 }}>{rowError[d.id]}</div>
          )}
        </td>
      </tr>
    );
  }

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 30, overflow: "auto",
      background: BB.bg, color: BB.fg,
      fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
    }}>
      <div style={{
        padding: "16px 24px", display: "flex", alignItems: "center",
        justifyContent: "space-between", borderBottom: `1px solid ${BB.border}`,
      }}>
        <div style={{ fontSize: 13, letterSpacing: 2, color: BB.dim }}>
          PENDING DRAFTS · {pending.length}
        </div>
        <div style={{ display: "flex", gap: 12 }}>
          <button onClick={load} style={ghostBtn}>
            <RefreshCw size={14} /> REFRESH
          </button>
          <button onClick={onClose} style={ghostBtn}>
            <X size={14} /> CLOSE
          </button>
        </div>
      </div>

      {error && (
        <div style={{ padding: "10px 24px", color: BB.red, fontSize: 11 }}>{error}</div>
      )}

      <div style={{ padding: 24 }}>
        {loading ? (
          <div style={{ color: BB.dim, fontSize: 11 }}>LOADING...</div>
        ) : pending.length === 0 ? (
          <div style={{ color: BB.dim, fontSize: 11, padding: "20px 0" }}>
            No pending drafts. Use the Claude Code plugin to book trades (coming in Plan 1b).
          </div>
        ) : (
          pendingGroups.map((g, gi) => (
            <div key={g.batchId || `single-${gi}`} style={{ marginBottom: 24 }}>
              <div style={{
                display: "flex", justifyContent: "space-between", alignItems: "center",
                color: BB.dim, fontSize: 11, letterSpacing: 1.5, padding: "8px 12px",
                background: BB.panelHead, borderBottom: `1px solid ${BB.border}`,
                border: `1px solid ${BB.border}`, borderBottomWidth: 0,
              }}>
                <span>
                  {g.isSingle
                    ? `SINGLE · ${fmtDate(g.list[0].created_at)}`
                    : `BATCH ${g.batchId.slice(0, 8)}… · ${g.list.length} DRAFTS · ${fmtDate(g.list[0].created_at)}`}
                </span>
                {!g.isSingle && (
                  <button style={primaryBtn} onClick={() => onApproveAll(g.list)}>
                    APPROVE ALL {g.list.length}
                  </button>
                )}
              </div>
              <table style={{ width: "100%", borderCollapse: "collapse", background: BB.panel, border: `1px solid ${BB.border}`, borderTop: 0 }}>
                <thead>
                  <tr>
                    <th style={th}>ID</th>
                    <th style={th}>SUMMARY</th>
                    <th style={th}>CREATED</th>
                    <th style={th}>DEAL REF / STATUS</th>
                    <th style={th}>ACTIONS</th>
                  </tr>
                </thead>
                <tbody>{g.list.map(renderRow)}</tbody>
              </table>
            </div>
          ))
        )}

        {/* APPROVED collapsed */}
        <div style={{ marginTop: 32 }}>
          <button style={ghostBtn} onClick={() => setShowApproved((s) => !s)}>
            {showApproved ? "HIDE" : "SHOW"} APPROVED ({approved.length})
          </button>
          {showApproved && approved.length > 0 && (
            <table style={{ width: "100%", borderCollapse: "collapse", background: BB.panel, marginTop: 12, border: `1px solid ${BB.border}` }}>
              <thead><tr>
                <th style={th}>ID</th><th style={th}>SUMMARY</th><th style={th}>DEAL REF</th><th style={th}>APPROVED BY</th><th style={th}>APPROVED AT</th>
              </tr></thead>
              <tbody>
                {approved.map((d) => (
                  <tr key={d.id}>
                    <td style={{ ...td, color: BB.dim }}>#{d.id}</td>
                    <td style={td}>{summarize(d.payload)}</td>
                    <td style={{ ...td, color: BB.green }}>{d.approved_deal_ref}</td>
                    <td style={td}>{d.approved_by || "—"}</td>
                    <td style={{ ...td, color: BB.dim }}>{fmtDate(d.approved_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* REJECTED collapsed */}
        <div style={{ marginTop: 16 }}>
          <button style={ghostBtn} onClick={() => setShowRejected((s) => !s)}>
            {showRejected ? "HIDE" : "SHOW"} REJECTED ({rejected.length})
          </button>
          {showRejected && rejected.length > 0 && (
            <table style={{ width: "100%", borderCollapse: "collapse", background: BB.panel, marginTop: 12, border: `1px solid ${BB.border}` }}>
              <thead><tr>
                <th style={th}>ID</th><th style={th}>SUMMARY</th><th style={th}>REASON</th><th style={th}>REJECTED BY</th><th style={th}>REJECTED AT</th>
              </tr></thead>
              <tbody>
                {rejected.map((d) => (
                  <tr key={d.id}>
                    <td style={{ ...td, color: BB.dim }}>#{d.id}</td>
                    <td style={td}>{summarize(d.payload)}</td>
                    <td style={{ ...td, color: BB.red }}>{d.rejection_reason || "—"}</td>
                    <td style={td}>{d.rejected_by || "—"}</td>
                    <td style={{ ...td, color: BB.dim }}>{fmtDate(d.rejected_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

    </div>
  );
}
