// Confirms with Tap that a charge was actually captured.
// The browser must never be trusted to declare a payment successful.
const TAP_SECRET = process.env.TAP_SECRET_KEY;

const BASE_URL = process.env.PUBLIC_BASE_URL || 'https://eilaji-payment.vercel.app';

const ALLOWED_ORIGINS = (process.env.ALLOWED_ORIGINS || BASE_URL)
  .split(',')
  .map((o) => o.trim())
  .filter(Boolean);

function applyCors(req, res) {
  const origin = req.headers.origin;
  if (origin && ALLOWED_ORIGINS.includes(origin)) {
    res.setHeader('Access-Control-Allow-Origin', origin);
    res.setHeader('Vary', 'Origin');
  }
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
}

// Tap charge IDs look like chg_TS0xxxxxxxxxxxxxx.
const CHARGE_ID_RE = /^[A-Za-z0-9_]{6,64}$/;

export default async function handler(req, res) {
  applyCors(req, res);
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  if (!TAP_SECRET) {
    console.error('TAP_SECRET_KEY is not set');
    return res.status(500).json({ success: false, error: 'Payment is not configured' });
  }

  try {
    const { tap_id: tapId } = req.body || {};

    if (!tapId || !CHARGE_ID_RE.test(String(tapId))) {
      return res.status(400).json({ success: false, error: 'No valid charge ID provided' });
    }

    const response = await fetch('https://api.tap.company/v2/charges/' + encodeURIComponent(tapId), {
      method:  'GET',
      headers: {
        'Authorization': 'Bearer ' + TAP_SECRET,
        'Content-Type':  'application/json',
      },
    });

    const charge = await response.json();

    // CAPTURED is the only status that means the money actually moved.
    if (charge && charge.status === 'CAPTURED') {
      return res.status(200).json({
        success:  true,
        plan:     charge.metadata && charge.metadata.plan,
        email:    charge.customer && charge.customer.email,
        amount:   charge.amount,
        currency: charge.currency,
      });
    }

    return res.status(200).json({
      success: false,
      status:  (charge && charge.status) || 'UNKNOWN',
      error:   'Payment not completed.',
    });

  } catch (err) {
    console.error('verify-payment error:', err.message);
    return res.status(500).json({ success: false, error: 'Could not verify the payment.' });
  }
}
