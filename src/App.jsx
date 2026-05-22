import React, { useEffect, useState } from "react";
import { AuthProvider, useAuth } from "./auth/AuthContext.jsx";
import LoginPage from "./auth/LoginPage.jsx";
import RegisterPage from "./auth/RegisterPage.jsx";
import TradeBookingForm from "./TradeBookingForm.jsx";

function Routed() {
  const { user, ready } = useAuth();
  const [expiredBanner, setExpiredBanner] = useState("");
  const [mode, setMode] = useState("login");          // "login" | "register"
  const [postRegisterBanner, setPostRegisterBanner] = useState("");

  useEffect(() => {
    function onExpired() { setExpiredBanner("Session expired — please sign in again"); }
    window.addEventListener("auth:expired", onExpired);
    return () => window.removeEventListener("auth:expired", onExpired);
  }, []);

  if (!ready) return <div style={{ background: "#000", minHeight: "100vh" }} />;

  if (!user) {
    // Auth pages get a thin fixed footer (short viewport, nothing to scroll
    // past). The authenticated app renders its own inline footer at the
    // bottom of the scroll container so it doesn't overlap the table.
    const authPage = mode === "register"
      ? (
        <RegisterPage
          onBackToLogin={() => setMode("login")}
          onRegistered={(msg) => { setPostRegisterBanner(msg); setMode("login"); }}
        />
      )
      : (
        <LoginPage
          banner={postRegisterBanner || expiredBanner}
          onSwitchToRegister={() => { setPostRegisterBanner(""); setMode("register"); }}
        />
      );
    return (
      <>
        {authPage}
        <AuthFooter />
      </>
    );
  }
  return <TradeBookingForm />;
}

// Fixed footer used only on the auth pages.
function AuthFooter() {
  return (
    <div style={{
      position: "fixed", bottom: 4, left: 0, right: 0,
      textAlign: "center", fontSize: 9, letterSpacing: 0.5,
      color: "#5d5d5d",
      fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
      pointerEvents: "none", zIndex: 1,
    }}>
      © 2026 Tokka Labs - Middle Office.
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <Routed />
    </AuthProvider>
  );
}
