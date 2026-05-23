import React, { useState } from "react";
import { Copy, X } from "lucide-react";
import { createToken } from "../auth/api.js";

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
  width: 460, padding: 20,
  fontFamily: "'IBM Plex Mono', ui-monospace, monospace", color: BB.fg, fontSize: 12,
};

const label = { display: "block", color: BB.dim, fontSize: 10, letterSpacing: 1.5, marginBottom: 6 };
const inputStyle = {
  background: BB.bg, color: BB.fg, border: `1px solid ${BB.border}`,
  padding: "8px 10px", width: "100%", fontFamily: "inherit", fontSize: 12, boxSizing: "border-box",
};
const primaryBtn = { background: BB.accent, color: BB.bg, border: "none", padding: "8px 16px", fontFamily: "inherit", fontSize: 11, letterSpacing: 1, cursor: "pointer" };
const ghostBtn   = { background: "transparent", color: BB.fg, border: `1px solid ${BB.border}`, padding: "8px 16px", fontFamily: "inherit", fontSize: 11, letterSpacing: 1, cursor: "pointer" };

export default function TokenGenerateModal({ onClose, onGenerated }) {
  const [name, setName] = useState("");
  const [days, setDays] = useState(90);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [plaintext, setPlaintext] = useState("");  // set after success → switches to reveal step
  const [copied, setCopied] = useState(false);

  async function onGenerate() {
    setError("");
    setBusy(true);
    const { status, body } = await createToken({ name: name.trim(), expires_in_days: days });
    setBusy(false);
    if (status !== 200 || !body?.ok) {
      setError(body?.error || `HTTP ${status}`);
      return;
    }
    setPlaintext(body.token);
    onGenerated?.();  // tell parent to refresh list in background
  }

  function onCopy() {
    navigator.clipboard.writeText(plaintext).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  // ── Step 2: reveal ─────────────────────────────────────────────
  if (plaintext) {
    return (
      <div style={overlay}>
        <div style={panel}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
            <div style={{ letterSpacing: 2, color: BB.dim, fontSize: 11 }}>TOKEN GENERATED — COPY NOW</div>
          </div>

          <div style={{
            background: BB.bg, border: `1px solid ${BB.border}`,
            padding: 12, wordBreak: "break-all", fontSize: 11, lineHeight: 1.6,
          }}>
            {plaintext}
          </div>

          <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
            <button style={ghostBtn} onClick={onCopy}>
              <Copy size={12} style={{ display: "inline", marginRight: 6, verticalAlign: -2 }} />
              {copied ? "COPIED" : "COPY"}
            </button>
          </div>

          <div style={{ color: BB.accent, fontSize: 11, marginTop: 16, lineHeight: 1.5 }}>
            ⚠ This token will NOT be shown again. Store it now (password manager, etc.).
          </div>

          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 16 }}>
            <button style={primaryBtn} onClick={onClose}>I'VE SAVED IT</button>
          </div>
        </div>
      </div>
    );
  }

  // ── Step 1: form ───────────────────────────────────────────────
  return (
    <div style={overlay}>
      <div style={panel}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <div style={{ letterSpacing: 2, color: BB.dim, fontSize: 11 }}>NEW API TOKEN</div>
          <button style={{ ...ghostBtn, padding: 4 }} onClick={onClose}><X size={12} /></button>
        </div>

        <div style={{ marginBottom: 14 }}>
          <span style={label}>NAME</span>
          <input
            style={inputStyle}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Alice's MacBook"
            autoFocus
            maxLength={64}
          />
        </div>

        <div style={{ marginBottom: 18 }}>
          <span style={label}>EXPIRES IN</span>
          <div style={{ display: "flex", gap: 12 }}>
            {[30, 90, 365].map((d) => (
              <label key={d} style={{ display: "flex", gap: 6, alignItems: "center", cursor: "pointer" }}>
                <input
                  type="radio"
                  name="days"
                  checked={days === d}
                  onChange={() => setDays(d)}
                />
                <span>{d === 365 ? "1 YEAR" : `${d} DAYS`}</span>
              </label>
            ))}
          </div>
        </div>

        {error && (
          <div style={{ color: BB.red, fontSize: 11, marginBottom: 12 }}>{error}</div>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button style={ghostBtn} onClick={onClose} disabled={busy}>CANCEL</button>
          <button
            style={primaryBtn}
            onClick={onGenerate}
            disabled={busy || !name.trim()}
          >
            {busy ? "GENERATING..." : "GENERATE"}
          </button>
        </div>
      </div>
    </div>
  );
}
