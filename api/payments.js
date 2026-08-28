/** GET /api/payments — transaction list for the dashboard (authorized).
 *  Optional ?slug= filters to a single link. */

const store = require('../lib/store');
const { cors, requireAuth } = require('../lib/http');

module.exports = async function handler(req, res) {
  cors(res);
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'GET') return res.status(405).json({ error: 'Method not allowed' });
  if (!requireAuth(req, res)) return;

  try {
    const slug = String((req.query && req.query.slug) || '').trim();
    let payments = await store.allPayments();
    if (slug) payments = payments.filter(function (p) { return p.slug === slug; });

    const captured = payments.filter(function (p) { return p.status === 'CAPTURED'; });
    const totals = captured.reduce(function (acc, p) {
      acc[p.currency] = Number(((acc[p.currency] || 0) + p.amount).toFixed(2));
      return acc;
    }, {});

    return res.status(200).json({
      payments: payments.slice(0, 200),
      summary: {
        count: payments.length,
        capturedCount: captured.length,
        totals: totals,
      },
    });
  } catch (err) {
    return res.status(500).json({ error: err.message });
  }
};
