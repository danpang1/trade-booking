import React, { useState } from "react";
import { apiJson } from "../auth/api.js";

const BB = { bg: "#000", panel: "#0a0a0a", border: "#1f1f1f", fg: "#e5e5e5", dim: "#7d7d7d", accent: "#FA8C16", red: "#FF4D4F" };

const input  = { width: "100%", padding: "8px 10px", background: "#000", color: BB.fg, border: `1px solid ${BB.border}`, outline: "none", fontFamily: "inherit", fontSize: 12 };
const ghost  = { background: "transparent", color: BB.fg, border: `1px solid ${BB.border}`, padding: "6px 12px", fontFamily: "inherit", fontSize: 11, letterSpacing: 1, cursor: "pointer" };
const primary = { background: BB.accent, color: BB.bg, border: "none", padding: "6px 14px", fontFamily: "inherit", fontSize: 11, letterSpacing: 1, cursor: "pointer", fontWeight: 600 };

function Field({ label, children }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 11, color: BB.dim, marginBottom: 4, letterSpacing: 1 }}>{label}</div>
      {children}
    </div>
  );
}

export default function UserEditModal({ mode, user, isLastAdmin, onClose, onSaved }) {
  const isCreate = mode === "create";
  const [username, setUsername] = useState(user?.username || "");
  const [email,    setEmail]    = useState(user?.email    || "");
  const [role,     setRole]     = useState(user?.role     || "user");
  const [password, setPassword] = useState("");
  const [showPw,   setShowPw]   = useState(false);
  const [error,    setError]    = useState("");
  const [pending,  setPending]  = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError("");
    setPending(true);
    let r;
    if (isCreate) {
      r = await apiJson("/api/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, email, role, password }),
      });
    } else {
      const body = { email, role };
      if (password) body.password = password;
      r = await apiJson(`/api/users/${user.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    }
    setPending(false);
    if (r.status === 200 && r.body?.ok) onSaved();
    else setError(r.body?.error || `HTTP ${r.status}`);
  }

  const demoteBlocked = !isCreate && isLastAdmin && role !== "admin";

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)",
      display: "flex", alignItems: "center", justifyContent: "center",
      zIndex: 1000,
    }}>
      <form onClick={(e) => e.stopPropagation()} onSubmit={submit} style={{
        width: 420, padding: 24, background: BB.panel,
        border: `1px solid ${BB.border}`,
        fontFamily: "var(--font-mono)", color: BB.fg,
      }}>
        <div style={{ fontSize: 13, letterSpacing: 2, color: BB.dim, marginBottom: 16 }}>
          {isCreate ? "NEW USER" : `EDIT USER #${user.id}`}
        </div>

        <Field label="Username">
          <input
            value={username} onChange={(e) => setUsername(e.target.value)}
            disabled={!isCreate || pending} style={input} autoFocus={isCreate}
          />
        </Field>
        <Field label="Email">
          <input
            type="email" value={email} onChange={(e) => setEmail(e.target.value)}
            disabled={pending} style={input}
          />
        </Field>
        <Field label="Role">
          <select
            value={role} onChange={(e) => setRole(e.target.value)}
            disabled={pending || (isLastAdmin && !isCreate)} style={input}
          >
            <option value="user">user</option>
            <option value="admin">admin</option>
          </select>
          {isLastAdmin && !isCreate && (
            <div style={{ color: BB.dim, fontSize: 10, marginTop: 4 }}>
              Cannot demote the last admin.
            </div>
          )}
        </Field>
        <Field label={isCreate ? "PASSWORD" : "PASSWORD (blank = unchanged)"}>
          <div style={{ display: "flex", gap: 6 }}>
            <input
              type={showPw ? "text" : "password"} value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={pending} style={{ ...input, flex: 1 }}
            />
            <button type="button" onClick={() => setShowPw((v) => !v)} style={ghost}>
              {showPw ? "HIDE" : "SHOW"}
            </button>
          </div>
        </Field>

        {error && (
          <div style={{ color: BB.red, fontSize: 11, marginTop: 10 }}>{error}</div>
        )}

        <div style={{ display: "flex", gap: 8, marginTop: 18, justifyContent: "flex-end" }}>
          <button type="button" onClick={onClose} style={ghost}>CANCEL</button>
          <button type="submit" disabled={pending || demoteBlocked} style={primary}>
            {pending ? "SAVING…" : isCreate ? "CREATE" : "SAVE"}
          </button>
        </div>
      </form>
    </div>
  );
}
