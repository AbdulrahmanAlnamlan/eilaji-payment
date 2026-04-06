// ⚠️  IMPORTANT: Replace TAP_SECRET below with your actual Tap secret key.
// Get it from: business.tap.company → Settings → API Credentials → Secret Key
// It starts with: sk_test_... (for testing) or sk_live_... (for live)

const TAP_SECRET = 'sk_live_Hc3XoBk1eLWip0j7OQRdElCA';

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  try {
    const { name, email, phone, phoneCode, plan, amount } = req.body;

    // Clean phone: digits only, max 8 digits for local number
    const localNumber = String(phone).replace(/\D/g, '');
    const countryCode = String(phoneCode || '974').replace(/\D/g, '');

    const nameParts  = String(name).trim().split(' ');
    const firstName  = nameParts[0] || name;
    const lastName   = nameParts.slice(1).join(' ') || firstName;

    const redirectUrl = 'https://eilaji-payment.vercel.app/?success=1&plan=' +
      encodeURIComponent(plan) + '&email=' + encodeURIComponent(email);

    const body = {
      amount:      Number(amount),
      currency:    'QAR',
      threeDSecure: true,
      save_card:   false,
      description: 'Eilaji ' + plan + ' Subscription',
      metadata:    { plan, name, email },
      customer: {
        first_name: firstName,
        last_name:  lastName,
        email:      email,
        phone: {
          country_code: countryCode,
          number:       localNumber,
        },
      },
      merchant:  { id: '21094672' },
      source:    { id: 'src_all' },
      redirect:  { url: redirectUrl },
      post:      { url: redirectUrl },
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

    // Return full Tap error for debugging
    return res.status(400).json({
      error: charge.message || charge.description || 'Payment failed',
      tap:   charge,
    });

  } catch (err) {
    return res.status(500).json({ error: err.message });
  }
}
