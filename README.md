# Tokka MO · Manual Trade Booking

Standalone React/Vite module for booking manual trades (SPOT / FUTURE / CASHFLOW / LOAN). Built to ship independently from the main `dashboard/` and to eventually wire into the planned `/api/bookings` FastAPI + Postgres backend.

## Run

```bash
npm install
npm run dev      # http://localhost:5180
npm run build    # → dist/
npm run preview  # serve built dist/
```

## Theme

Bloomberg-terminal aesthetic — black canvas, orange (`#FA8C16`) primary accent, cyan/amber/green/red data colors, sharp rectangular inputs, JetBrains Mono throughout. All theme tokens live in the `BB` constants block at the top of `src/TradeBookingForm.jsx` — nothing leaks to global CSS.

## Wire-up status

Frontend-only at this point. The "Book Trade" button currently just flips `status → BOOKED` locally and updates the JSON preview. Planned backend:

- `POST /api/bookings` (multipart: record JSON + file attachments)
- Postgres `bookings` table (one row, JSONB `payload` per category)
- Google Drive service account → per-`trade_id` folder for term sheets / invoices / agreements
- Reference data from `tq_oms_data` Postgres (323 active accounts, ~90 venues, 724 instruments) — to populate dropdowns
