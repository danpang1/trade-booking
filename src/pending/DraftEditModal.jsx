import React, { useEffect, useState } from "react";
import { X } from "lucide-react";
import { getDraft, patchDraft, approveDraft, rejectDraft } from "../auth/api.js";

const BB = {
  bg: "#000", panel: "#0a0a0a", border: "#1f1f1f",
  fg: "#e5e5e5", dim: "#7d7d7d", accent: "#FA8C16", red: "#FF4D4F",
};

const overlay = {
  position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)",
  display: "flex", alignItems: "center", justifyContent: "center", zIndex: 50,
};

const panel = {
  background: BB.panel, border: `1px solid ${BB.border}`,
  width: 540, maxHeight: "90vh", overflow: "auto", padding: 20,
  fontFamily: "var(--font-mono)",
  color: BB.fg, fontSize: 12,
};

const label = { display: "block", color: BB.dim, fontSize: 10, letterSpacing: 1.5, marginBottom: 6 };
const inputStyle = {
  background: BB.bg, color: BB.fg, border: `1px solid ${BB.border}`,
  padding: "8px 10px", width: "100%", fontFamily: "inherit", fontSize: 12, boxSizing: "border-box",
};
const primaryBtn = { background: BB.accent, color: BB.bg, border: "none", padding: "8px 16px", fontFamily: "inherit", fontSize: 11, letterSpacing: 1, cursor: "pointer" };
const ghostBtn   = { background: "transparent", color: BB.fg, border: `1px solid ${BB.border}`, padding: "8px 16px", fontFamily: "inherit", fontSize: 11, letterSpacing: 1, cursor: "pointer" };
const redBtn     = { background: "transparent", color: BB.red, border: `1px solid ${BB.red}`, padding: "8px 16px", fontFamily: "inherit", fontSize: 11, letterSpacing: 1, cursor: "pointer" };

// Editable subset of CASHFLOW payload fields. For full editing the
// user opens the row in TradeBookingForm via "Open in form".
const EDITABLE_FIELDS = [
  { key: "cashflow_type",   label: "CASHFLOW TYPE" },
  { key: "direction",       label: "DIRECTION (INCOMING/OUTGOING)" },
  { key: "entity",          label: "ENTITY" },
  { key: "portfolio_id",    label: "PORTFOLIO ID" },
  { key: "portfolio_name",  label: "PORTFOLIO NAME" },
  { key: "counterparty",    label: "COUNTERPARTY" },
  { key: "asset",           label: "ASSET" },
  { key: "amount",          label: "AMOUNT" },
  { key: "trade_date",      label: "TRADE DATE (ISO)" },
  { key: "value_date",      label: "VALUE DATE (ISO)" },
  { key: "comment",         label: "COMMENT" },
];

export default function DraftEditModal({ draftId, onClose, onSaved, onApproved, onRejected }) {
  const [draft, setDraft]   = useState(null);
  const [edited, setEdited] = useState({});
  const [busy, setBusy]     = useState(false);
  const [error, setError]   = useState("");

  useEffect(() => {
    (async () => {
      const { status, body } = await getDraft(draftId);
      if (status !== 200 || !body?.ok) {
        setError(body?.error || `HTTP ${status}`);
        return;
      }
      setDraft(body.draft);
      setEdited({ ...body.draft.payload });
    })();
  }, [draftId]);

  function setField(key, val) {
    setEdited((cur) => ({ ...cur, [key]: val }));
  }

  async function onSave() {
    setBusy(true);
    setError("");
    const { status, body } = await patchDraft(draftId, edited);
    setBusy(false);
    if (status !== 200 || !body?.ok) {
      setError(body?.error || `HTTP ${status}`);
      return;
    }
    onSaved?.();
    onClose();
  }

  async function onApprove() {
    if (!confirm("Approve and book this draft? This inserts into trades_cashflow.")) return;
    setBusy(true);
    setError("");
    const { status, body } = await approveDraft(draftId);
    setBusy(false);
    if (status !== 200 || !body?.ok) {
      setError(body?.error || `HTTP ${status}`);
      return;
    }
    onApproved?.(body.deal_ref);
    onClose();
  }

  async function onReject() {
    const reason = prompt("Reason for rejection (optional):") ?? null;
    setBusy(true);
    setError("");
    const { status, body } = await rejectDraft(draftId, reason);
    setBusy(false);
    if (status !== 200 || !body?.ok) {
      setError(body?.error || `HTTP ${status}`);
      return;
    }
    onRejected?.();
    onClose();
  }

  if (!draft && !error) {
    return (
      <div style={overlay}>
        <div style={panel}>
          <div style={{ color: BB.dim, fontSize: 11 }}>LOADING...</div>
        </div>
      </div>
    );
  }

  return (
    <div style={overlay}>
      <div style={panel}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <div style={{ letterSpacing: 2, color: BB.dim, fontSize: 11 }}>
            EDIT DRAFT #{draftId}
          </div>
          <button style={{ ...ghostBtn, padding: 4 }} onClick={onClose}><X size={12} /></button>
        </div>

        {error && (
          <div style={{ color: BB.red, fontSize: 11, marginBottom: 12 }}>{error}</div>
        )}

        {draft && (
          <>
            {EDITABLE_FIELDS.map((f) => (
              <div key={f.key} style={{ marginBottom: 10 }}>
                <span style={label}>{f.label}</span>
                <input
                  style={inputStyle}
                  value={edited[f.key] ?? ""}
                  onChange={(e) => setField(f.key, e.target.value)}
                />
              </div>
            ))}

            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 18, gap: 8 }}>
              <button style={redBtn} onClick={onReject} disabled={busy}>REJECT</button>
              <div style={{ display: "flex", gap: 8 }}>
                <button style={ghostBtn} onClick={onSave} disabled={busy}>
                  {busy ? "..." : "SAVE DRAFT"}
                </button>
                <button style={primaryBtn} onClick={onApprove} disabled={busy}>
                  {busy ? "..." : "APPROVE & BOOK"}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
