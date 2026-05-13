import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import TradeBookingForm from "./TradeBookingForm.jsx";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <TradeBookingForm />
  </StrictMode>
);
