import React, { useEffect, useState } from "react";
import { AuthProvider, useAuth } from "./auth/AuthContext.jsx";
import LoginPage from "./auth/LoginPage.jsx";
import TradeBookingForm from "./TradeBookingForm.jsx";

function Routed() {
  const { user, ready } = useAuth();
  const [expiredBanner, setExpiredBanner] = useState("");

  useEffect(() => {
    function onExpired() { setExpiredBanner("Session expired — please sign in again"); }
    window.addEventListener("auth:expired", onExpired);
    return () => window.removeEventListener("auth:expired", onExpired);
  }, []);

  if (!ready) return <div style={{ background: "#000", minHeight: "100vh" }} />;

  if (!user) return <LoginPage banner={expiredBanner} />;
  return <TradeBookingForm />;
}

export default function App() {
  return (
    <AuthProvider>
      <Routed />
    </AuthProvider>
  );
}
