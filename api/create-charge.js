// Creates a Tap charge and returns the hosted payment page URL.
// The secret key MUST come from the environment — never commit it.
const TAP_SECRET = process.env.TAP_SECRET_KEY;

// Prices live on the server. The browser sends a plan ID, never an amount,
// so a tampered request can't buy a yearly plan for 1 QAR.
const PLANS = {
  monthly:  { amount: 29,  label: 'Monthly'  },
  '3months':{ amount: 75,  label: '3 Months' },
  yearly:   { amount: 199, label: 'Yearly'   },
};

const BASE_URL = process.env.PUBLIC_BASE_URL || 'https://eilaji-payment.vercel.app';

// Only our own site may call this endpoint from a browser.
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

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default async function handler(req, res) {
  applyCors(req, res);
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  if (!TAP_SECRET) {
    console.error('TAP_SECRET_KEY is not set');
    return res.status(500).json({ error: 'Payment is not configured' });
  }

  try {
    const { name, email, phone, phoneCode, plan } = req.body || {};

    const selected = PLANS[plan];
    if (!selected) return res.status(400).json({ error: 'Unknown plan' });

    const cleanEmail = String(email || '').trim();
    if (!EMAIL_RE.test(cleanEmail)) {
      return res.status(400).json({ error: 'A valid email is required' });
    }

    const nameParts = String(name || '').trim().split(/\s+/).filter(Boolean);
    const firstName = nameParts[0] || 'Customer';
    const lastName = nameParts.slice(1).join(' ') || firstName;

    // Phone: digits only.
    const rawPhone = String(phone || '').replace(/\D/g, '');
    const rawCode = String(phoneCode || '974').replace(/\D/g, '');
    if (rawPhone.length < 6) {
      return res.status(400).json({ error: 'A valid phone number is required' });
    }

    // No email or name in the redirect URL — it ends up in browser history and
    // referrer headers. The verify endpoint reads those back from Tap instead.
    const redirectUrl = BASE_URL + '/?success=1';

    const body = {
      amount:       selected.amount,
      currency:     'QAR',
      threeDSecure: true,
      save_card:    false,
      description:  'Eilaji ' + selected.label + ' Subscription',
      metadata:     { plan },
      customer: {
        first_name: firstName,
        last_name:  lastName,
        email:      cleanEmail,
        phone: { country_code: rawCode, number: rawPhone },
      },
      source:   { id: 'src_all' },
      redirect: { url: redirectUrl },
    };

    const response = await fetch('https://api.tap.company/v2/charges', {
      method:  'POST',
      headers: {
        'Authorization': 'Bearer ' + TAP_SECRET,
        'Content-Type':  'application/json',
      },
      body: JSON.stringify(body),
    });

    const charge = await response.json();

    if (charge && charge.transaction && charge.transaction.url) {
      return res.status(200).json({ url: charge.transaction.url });
    }

    // Log the failure for us; return a generic message to the browser so we
    // don't leak Tap's internals (or anything key-shaped) to the client.
    console.error('Tap charge failed', {
      plan,
      status: response.status,
      tapError: charge && (charge.errors || charge.message || charge.description),
    });
    return res.status(400).json({ error: 'Could not start the payment. Please try again.' });

  } catch (err) {
    console.error('create-charge error:', err.message);
    return res.status(500).json({ error: 'Could not start the payment. Please try again.' });
  }
}
