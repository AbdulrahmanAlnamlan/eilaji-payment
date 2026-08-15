# Eilaji Payment

Bilingual (Arabic/English, RTL) subscription checkout page for Eilaji Premium,
using [Tap Payments](https://www.tap.company/) and deployed on Vercel.

## Structure

| Path                    | What it does |
| ----------------------- | ------------ |
| `index.html`            | The whole front end — plan picker, form, country codes, result screen. |
| `api/create-charge.js`  | Creates a Tap charge, returns the hosted payment page URL. |
| `api/verify-payment.js` | Asks Tap whether a charge was actually `CAPTURED`. |
| `vercel.json`           | Routes `/api/*` to functions, everything else to `index.html`. |

## Setup

1. Copy `.env.example` to `.env` and fill in your Tap key.
2. In Vercel, add the same variables under **Settings → Environment Variables**.
   Use a `sk_test_` key for Preview/Development and the `sk_live_` key for
   Production only.
3. Deploy.

There are no runtime dependencies to install.

## Payment flow

1. The browser POSTs `{name, email, phone, phoneCode, plan}` to `/api/create-charge`.
   **It does not send an amount** — prices live in the `PLANS` table in
   `api/create-charge.js` so the price cannot be tampered with client-side.
2. The server creates the charge and returns Tap's hosted payment URL.
3. Tap redirects back to `/?success=1&tap_id=chg_...`.
4. The browser POSTs `tap_id` to `/api/verify-payment`, which asks Tap for the
   charge. Only status `CAPTURED` shows the success screen.

`?success=1` on its own proves nothing — step 4 is what makes the result real.

## Changing prices

Edit `PLANS` in `api/create-charge.js` **and** the `PLANS` object in
`index.html`. The server table is the one that decides what the customer is
actually charged; the front-end one is display only. Keep them in sync.

## Security notes

- Secret keys come from `process.env.TAP_SECRET_KEY`. Never hardcode them —
  this repo is public.
- CORS is restricted to `ALLOWED_ORIGINS` (defaults to `PUBLIC_BASE_URL`).
- Request/response bodies are not logged, so customer name, email, and phone
  stay out of the deployment logs.
- Tap's raw error payloads are logged server-side but never returned to the
  browser.
