const TAP_SECRET = 'sk_test_YNWTmzgcVJZvdtAErXk5KU2';

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  try {
    const { name, email, phone, phoneCode, plan, amount } = req.body;

    // Clean inputs
    const nameParts = String(name || '').trim().split(' ');
    const firstName = nameParts[0] || 'Customer';
    const lastName  = nameParts.slice(1).join(' ') || firstName;

    // Phone: digits only, remove leading zeros
    const rawPhone   = String(phone || '').replace(/\D/g, '');
    const rawCode    = String(phoneCode || '974').replace(/\D/g, '');

    const redirectUrl = 'https://eilaji-payment.vercel.app/?success=1&plan=' +
      encodeURIComponent(plan || '') + '&email=' + encodeURIComponent(email || '');

    const body = {
      amount:       Number(amount),
      currency:     'QAR',
      threeDSecure: true,
      save_card:    false,
      description:  'Eilaji ' + (plan || '') + ' Subscription',
      customer: {
        first_name: firstName,
        last_name:  lastName,
        email:      String(email || '').trim(),
        phone: {
          country_code: rawCode,
          number:       rawPhone,
        },
      },
      source:   { id: 'src_all' },
      redirect: { url: redirectUrl },
    };

    console.log('Tap request body:', JSON.stringify(body, null, 2));

    const response = await fetch('https://api.tap.company/v2/charges', {
      method:  'POST',
      headers: {
        'Authorization': 'Bearer ' + TAP_SECRET,
        'Content-Type':  'application/json',
      },
      body: JSON.stringify(body),
    });

    const charge = await response.json();

    console.log('Tap response:', JSON.stringify(charge, null, 2));

    if (charge && charge.transaction && charge.transaction.url) {
      return res.status(200).json({ url: charge.transaction.url });
    }

    // Return full Tap error so we can see what's wrong
    return res.status(400).json({
      error:   charge.message || charge.description || JSON.stringify(charge),
      details: charge,
    });

  } catch (err) {
    console.error('Server error:', err);
    return res.status(500).json({ error: err.message });
  }
}
