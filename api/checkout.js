/**
 * POST /api/checkout — mock payment authorization for a hosted link.
 *
 * No money moves. The outcome is decided by deterministic rules so a demo can
 * show both a success and a decline on purpose:
 *   - card ending 0002 → DECLINED
 *   - card ending 0069 → DECLINED (insufficient funds)
 *   - any other 12+ digit card, or a non-card method → CAPTURED
 *
 * The response shape deliberately mirrors what a real gateway returns
 * (id, status, amount, currency, method), so swapping this handler for SADAD
 * or Tap later is a change in one file rather than across the front end.
 */

const store = require('../lib/store');
const { cors, body, randomId } = require('../lib/http');

// The methods SADAD itself settles: the national debit network, the two card
// schemes, both wallets, and SADAD's own stored-value wallet.
const METHODS = ['naps', 'card', 'applepay', 'googlepay', 'sadad_wallet'];

function decide(method, cardNumber) {
  if (method !== 'card' && method !== 'naps') {
    return { status: 'CAPTURED' };
  }
  const digits = String(cardNumber || '').replace(/\D/g, '');
  if (digits.length < 12) {
    return { status: 'FAILED', reason: 'INVALID_CARD_NUMBER' };
  }
  if (digits.endsWith('0002')) {
    return { status: 'DECLINED', reason: 'DO_NOT_HONOUR' };
  }
  if (digits.endsWith('0069')) {
    return { status: 'DECLINED', reason: 'INSUFFICIENT_FUNDS' };
  }
  return { status: 'CAPTURED' };
}

function resolveAmount(link, input) {
  if (link.pricing === 'plans') {
    const plan = (link.plans || []).find(function (p) { return p.id === input.planId; });
    if (!plan) return { error: 'Choose one of the available plans' };
    return { amount: Number(plan.amount), planId: plan.id, planName: plan.nameEn || plan.name };
  }
  if (link.pricing === 'open') {
    const amount = Number(input.amount);
    if (!(amount > 0)) return { error: 'Enter an amount above zero' };
    if (amount > 100000) return { error: 'Amount exceeds the per-transaction limit' };
    return { amount: amount };
  }
  return { amount: Number(link.amount) };
}

module.exports = async function handler(req, res) {
  cors(res);
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  try {
    const input = body(req);
    const link = await store.getLink(String(input.slug || ''));
    if (!link) return res.status(404).json({ error: 'Link not found' });
    if (!link.active) return res.status(410).json({ error: 'This payment link is no longer active' });

    const method = METHODS.indexOf(input.method) === -1 ? 'card' : input.method;

    const priced = resolveAmount(link, input);
    if (priced.error) return res.status(400).json({ error: priced.error });

    if (link.collectName && !String(input.name || '').trim()) {
      return res.status(400).json({ error: 'Name is required' });
    }
    if (link.collectEmail && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(String(input.email || '').trim())) {
      return res.status(400).json({ error: 'A valid email is required' });
    }
    if (link.collectPhone && String(input.phone || '').replace(/\D/g, '').length < 6) {
      return res.status(400).json({ error: 'A valid phone number is required' });
    }

    const outcome = decide(method, input.cardNumber);
    const digits = String(input.cardNumber || '').replace(/\D/g, '');

    const payment = {
      id: randomId('pay'),
      slug: link.slug,
      linkTitle: link.titleEn || link.title,
      amount: priced.amount,
      currency: link.currency,
      planId: priced.planId || '',
      planName: priced.planName || '',
      method: method,
      last4: digits ? digits.slice(-4) : '',
      status: outcome.status,
      reason: outcome.reason || '',
      customer: {
        name: String(input.name || '').slice(0, 120),
        email: String(input.email || '').slice(0, 160),
        phone: String(input.phoneCode || '') + String(input.phone || '').replace(/\D/g, ''),
        note: String(input.note || '').slice(0, 400),
      },
      mock: true,
      createdAt: new Date().toISOString(),
    };

    await store.addPayment(payment);

    if (outcome.status === 'CAPTURED') {
      link.paidCount = (link.paidCount || 0) + 1;
      link.paidTotal = Number(((link.paidTotal || 0) + priced.amount).toFixed(2));
      await store.putLink(link);
    }

    return res.status(200).json({
      id: payment.id,
      status: payment.status,
      reason: payment.reason,
      amount: payment.amount,
      currency: payment.currency,
      method: payment.method,
      mock: true,
      redirectUrl: outcome.status === 'CAPTURED' ? link.redirectUrl || '' : '',
    });
  } catch (err) {
    return res.status(500).json({ error: err.message });
  }
};
