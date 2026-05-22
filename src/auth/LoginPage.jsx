import React, { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import tokkaLogo from "../assets/tokka-labs-logo.png";
import { useAuth } from "./AuthContext.jsx";

// Bloomberg-terminal palette — mirror TradeBookingForm constants.
const BB = {
  bg:     "#000000",
  fg:     "#e5e5e5",
  dim:    "#7d7d7d",
  panel:  "#0a0a0a",
  border: "#1f1f1f",
  accent: "#1f63ea",  // tokka blue (sampled from logo; matches TradeBookingForm)
  red:    "#FF4D4F",
};

const inputStyle = {
  width: "100%", padding: "8px 10px", background: "#000",
  color: "#e5e5e5", border: "1px solid #1f1f1f", outline: "none",
  fontFamily: "inherit", fontSize: 13,
};

export default function LoginPage({ banner, onSwitchToRegister }) {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError]       = useState("");
  const [pending, setPending]   = useState(false);
  const [showPw, setShowPw]     = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError("");
    setPending(true);
    const r = await login(username.trim(), password);
    setPending(false);
    if (!r.ok) setError(r.error);
  }

  return (
    <div style={{
      minHeight: "100vh", background: BB.bg, color: BB.fg,
      display: "flex", alignItems: "center", justifyContent: "center",
      fontFamily: "'JetBrains Mono', monospace",
    }}>
      <form onSubmit={submit} style={{
        width: 360, padding: 32, background: BB.panel,
        border: `1px solid ${BB.border}`,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 24 }}>
          <img src={tokkaLogo} alt="Tokka" style={{ height: 28 }} />
          <div style={{ fontSize: 13, color: BB.dim, letterSpacing: 1.2 }}>TRADE BOOKING</div>
        </div>

        {banner && (
          <div style={{
            marginBottom: 16, padding: "8px 12px",
            background: "#04162a", border: `1px solid ${BB.accent}`,
            color: BB.accent, fontSize: 12,
          }}>{banner}</div>
        )}

        <label style={{ display: "block", fontSize: 11, color: BB.dim, marginBottom: 4 }}>USERNAME</label>
        <input
          autoFocus value={username} onChange={(e) => setUsername(e.target.value)}
          style={inputStyle} disabled={pending}
        />

        <label style={{ display: "block", fontSize: 11, color: BB.dim, marginBottom: 4, marginTop: 16 }}>PASSWORD</label>
        <div style={{ position: "relative" }}>
          <input
            type={showPw ? "text" : "password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={{ ...inputStyle, paddingRight: 36 }}
            disabled={pending}
          />
          <button
            type="button"
            tabIndex={-1}
            onClick={() => setShowPw((v) => !v)}
            title={showPw ? "Hide password" : "Show password"}
            style={{
              position: "absolute", right: 6, top: "50%", transform: "translateY(-50%)",
              background: "transparent", border: "none", color: BB.dim, cursor: "pointer",
              padding: 4, display: "flex", alignItems: "center",
            }}
          >
            {showPw ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
        </div>

        {error && (
          <div style={{ marginTop: 14, color: BB.red, fontSize: 12 }}>{error}</div>
        )}

        <button type="submit" disabled={pending || !username || !password} style={{
          width: "100%", marginTop: 20, padding: "10px 16px",
          background: BB.accent, color: BB.bg, border: "none",
          fontFamily: "inherit", fontSize: 13, fontWeight: 600, letterSpacing: 1,
          cursor: pending ? "wait" : "pointer", opacity: pending ? 0.6 : 1,
        }}>
          {pending ? "SIGNING IN…" : "SIGN IN"}
        </button>

        {onSwitchToRegister && (
          <button type="button" onClick={onSwitchToRegister} disabled={pending} style={{
            width: "100%", marginTop: 10, padding: "8px 16px",
            background: "transparent", color: BB.dim, border: "none",
            fontFamily: "inherit", fontSize: 11, letterSpacing: 1.5, cursor: "pointer",
          }}>
            REQUEST ACCOUNT →
          </button>
        )}
      </form>
    </div>
  );
}
