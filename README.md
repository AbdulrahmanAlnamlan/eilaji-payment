# Eilaji Pay — payment-link platform

A payment-link platform in the shape of SADAD's: a merchant dashboard where you
create branded links, and a hosted checkout page per link that a customer opens
from WhatsApp, an Instagram bio, or a printed QR code.

Built for **Dr. Abdulrahman Alnamlan's** consultation services, with the existing
Eilaji Premium subscription kept as a third link.

> **Payments are mocked.** `api/checkout.js` decides the outcome from the card
> number and writes a transaction record. No gateway is called, no card data
> leaves the browser, and no money moves. See *Going live* below.

## Pages

| Route | What it is |
| --- | --- |
| `/` | Platform landing page — services, payment methods, demo links |
| `/dashboard` | Merchant dashboard — links, transactions, link builder (passcode) |
| `/p/<slug>` | Hosted checkout page for one link |
| `/eilaji` | The original Tap-backed Eilaji subscription page, kept as-is |

Every page is bilingual Arabic/English with a full RTL/LTR flip, and the choice
is remembered across pages.

## Services covered

| Service | State |
| --- | --- |
| Payment links — fixed amount, payer-chosen amount, or multiple plans | working |
| Hosted checkout with a 3-D Secure step | working (simulated) |
| Invoicing — transaction ID and on-screen receipt | working |
| Merchant dashboard — views, captures, declines, totals per currency | working |
| Point of sale — printable QR per link | working |
| Payment methods — NAPS, Visa, Mastercard, Apple Pay, Google Pay, wallet | selectable, settlement mocked |

## Running it

```bash
npm run dev     # http://localhost:3000
npm test        # 24 API checks against a throwaway server
```

The dashboard passcode is `demo1234` unless `MERCHANT_PASSCODE` is set.

Test cards on the checkout page:

| Card | Result |
| --- | --- |
| `4242 4242 4242 4242` | captured |
| `4000 0000 0000 0002` | declined — do not honour |
| `4000 0000 0000 0069` | declined — insufficient funds |

Apple Pay, Google Pay, and the wallet always capture; they take no card number.

## Layout

```
index.html          landing page
dashboard.html      merchant dashboard
pay.html            hosted checkout
eilaji.html         original Tap subscription page
assets/             shared stylesheet, bilingual switch, country dial codes
api/links.js        list + create links          (passcode)
api/link.js         read + update + delete one   (read is public)
api/checkout.js     mock payment authorization   (public)
api/payments.js     transaction list             (passcode)
api/create-charge.js, api/verify-payment.js      legacy Tap handlers
lib/store.js        storage: Vercel KV, or process memory
lib/http.js         auth, CORS, body parsing, slugs
scripts/dev-server.js, scripts/smoke-test.js
```

## Storage

With `KV_REST_API_URL` and `KV_REST_API_TOKEN` set, links and payments persist in
Vercel KV / Upstash. Without them the store lives in process memory and resets on
every cold start — fine for a demo, not for anything real. `lib/store.js` keeps
each collection in a single JSON blob; move to per-row keys before this holds a
meaningful number of links.

## Going live

1. **Rotate the Tap key.** A live `sk_live_…` secret was committed to this repo's
   history and must be treated as compromised — rotate it in the Tap dashboard.
   The handlers now read `process.env.TAP_SECRET`, so set that in Vercel.
2. **Set `MERCHANT_PASSCODE`.** The `demo1234` fallback is refused when
   `NODE_ENV=production`, so the dashboard is unreachable until you set one. A
   single shared passcode is demo-grade; real merchant accounts need real auth.
3. **Replace `api/checkout.js`.** It returns the same shape a gateway does
   (`id`, `status`, `amount`, `currency`, `method`), so swapping in SADAD or Tap
   is a change in that one file. Take card data with the provider's hosted fields
   or SDK — never post a PAN to your own server, which is what the mock does.
4. **Attach KV** so links and transactions survive a cold start.
5. Wire receipts (email/SMS) and webhook verification for asynchronous captures.
