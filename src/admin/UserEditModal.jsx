import React, { useState } from "react";
import { apiJson } from "../auth/api.js";

// Token-backed palette — mirrors UserAdmin / ApiTokens. The old dark
// Bloomberg theme is gone; primary CTAs sit on --panel, inputs on
// --paper, and errors use --signal-sell.

const overlay = {
  position: "fixed", inset: 0, background: "rgba(13,13,13,0.45)",
  display: "flex", alignItems: "flex-start", justifyContent: "center",
  paddingTop: 80,  // ~clear the top chrome / UTC clock
  zIndex: 1000,
};

const panel = {
  width: 460, padding: 24,
  background: "var(--paper)",
  border: "1px solid var(--rule-2)", borderRadius: 3,
  fontFamily: "var(--font-mono)", color: "var(--ink)", fontSize: 12,
  boxShadow: "0 24px 60px rgba(13,13,13,0.18)",
};

const inputStyle = {
  width: "100%",
  padding: "8px 10px",
  background: "var(--paper)", color: "var(--ink)",
  border: "1px solid var(--rule-2)", borderRadius: 3,
  outline: "none", fontFamily: "var(--font-mono)", fontSize: 12,
  boxSizing: "border-box",
};

const primary = { background: "var(--panel)", color: "var(--panel-ink)", border: "1px solid var(--panel)", padding: "6px 14px", fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.05em", textTransform: "uppercase", cursor: "pointer", fontWeight: 600, borderRadius: 3 };
const ghost   = { background: "var(--paper)", color: "var(--ink)", border: "1px solid var(--rule-2)", padding: "6px 12px", fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.05em", textTransform: "uppercase", cursor: "pointer", borderRadius: 3 };

function Field({ label, children }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{
        fontSize: 10, color: "var(--ink-3)",
        letterSpacing: "0.08em", textTransform: "uppercase",
        marginBottom: 4,
      }}>{label}</div>
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
    <div onClick={onClose} style={overlay}>
      <form onClick={(e) => e.stopPropagation()} onSubmit={submit} style={panel}>
        <div style={{
          fontFamily: "var(--font-serif)",
          fontSize: 18, fontWeight: 600, color: "var(--ink)",
          letterSpacing: "-0.01em",
          marginBottom: 4,
        }}>
          {isCreate ? "New user" : `Edit user #${user.id}`}
        </div>
        <div style={{
          fontSize: 10, color: "var(--ink-3)",
          letterSpacing: "0.08em", textTransform: "uppercase",
          marginBottom: 16,
        }}>
          {isCreate ? "Create an operator account" : `Update ${user.username}`}
        </div>

        <Field label="Username">
          <input
            value={username} onChange={(e) => setUsername(e.target.value)}
            disabled={!isCreate || pending}
            style={{
              ...inputStyle,
              background: (!isCreate || pending) ? "var(--paper-2)" : "var(--paper)",
              color: (!isCreate || pending) ? "var(--ink-3)" : "var(--ink)",
            }}
            autoFocus={isCreate}
          />
        </Field>
        <Field label="Email">
          <input
            type="email" value={email} onChange={(e) => setEmail(e.target.value)}
            disabled={pending}
            style={inputStyle}
          />
        </Field>
        <Field label="Role">
          <select
            value={role} onChange={(e) => setRole(e.target.value)}
            disabled={pending || (isLastAdmin && !isCreate)}
            style={inputStyle}
          >
            <option value="user">user</option>
            <option value="admin">admin</option>
          </select>
          {isLastAdmin && !isCreate && (
            <div style={{ color: "var(--ink-3)", fontSize: 10, marginTop: 4 }}>
              Cannot demote the last admin.
            </div>
          )}
        </Field>
        <Field label={isCreate ? "Password" : "Password (blank = unchanged)"}>
          <div style={{ display: "flex", gap: 6 }}>
            <input
              type={showPw ? "text" : "password"} value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={pending}
              style={{ ...inputStyle, flex: 1 }}
            />
            <button type="button" onClick={() => setShowPw((v) => !v)} style={ghost}>
              {showPw ? "Hide" : "Show"}
            </button>
          </div>
        </Field>

        {error && (
          <div style={{
            padding: "8px 10px", marginTop: 12,
            background: "var(--signal-sell-bg)",
            color: "var(--signal-sell)",
            border: "1px solid var(--signal-sell)",
            borderRadius: 3, fontSize: 11,
          }}>{error}</div>
        )}

        <div style={{ display: "flex", gap: 8, marginTop: 18, justifyContent: "flex-end" }}>
          <button type="button" onClick={onClose} style={ghost}>Cancel</button>
          <button type="submit" disabled={pending || demoteBlocked} style={{
            ...primary,
            opacity: (pending || demoteBlocked) ? 0.5 : 1,
            cursor: (pending || demoteBlocked) ? "not-allowed" : "pointer",
          }}>
            {pending ? "Saving…" : isCreate ? "Create" : "Save"}
          </button>
        </div>
      </form>
    </div>
  );
}
