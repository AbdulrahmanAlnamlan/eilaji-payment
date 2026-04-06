export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const TAP_SECRET = 'sk_test_XKokBfNWv6FIYuTMg5sLPjhJ';

  try {
    const { name, email, phone, phoneCode, plan, amount, lang } = req.body;

    const cleanPhone = phone.replace(/\D/g, '').slice(-8);
    const cleanCode  = (phoneCode || '+974').replace('+', '');

    const response = await fetch('https://api.tap.company/v2/charges', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + TAP_SECRET,
        'Content-Type':  'application/json',
      },
      body: JSON.stringify({
        amount:   amount,
        currency: 'QAR',
        customer: {
          first_name: name.split(' ')[0],
          last_name:  name.split(' ').slice(1).join(' ') || '-',
          email:      email,
          phone: { country_code: cleanCode, number: cleanPhone },
        },
        source:   { id: 'src_all' },
        redirect: {
          url: 'https://eilaji-payment.vercel.app/?success=1&plan=' + plan + '&email=' + encodeURIComponent(email),
        },
        description: 'Eilaji ' + plan + ' Subscription',
        metadata:    { plan, lang, name, email },
      }),
    });

    const charge = await response.json();

    if (charge.transaction && charge.transaction.url) {
      return res.status(200).json({ url: charge.transaction.url });
    } else {
      return res.status(400).json({ error: charge.message || 'Payment failed' });
    }
  } catch (err) {
    return res.status(500).json({ error: err.message });
  }
}
