/** GET  /api/links  → every link belonging to the merchant (dashboard, authorized)
 *  POST /api/links  → create a link (dashboard, authorized) */

const store = require('../lib/store');
const { cors, requireAuth, body, slugify, randomId } = require('../lib/http');

const CURRENCIES = ['QAR', 'SAR', 'AED', 'KWD', 'BHD', 'OMR', 'USD', 'EUR'];
const PRICING = ['fixed', 'open', 'plans'];

function normalizePlans(input) {
  if (!Array.isArray(input)) return [];
  return input
    .filter(function (p) { return p && Number(p.amount) > 0; })
    .slice(0, 6)
    .map(function (p, i) {
      return {
        id: slugify(p.id || p.nameEn || p.name) || 'plan' + (i + 1),
        name: String(p.name || p.nameEn || '').slice(0, 60),
        nameEn: String(p.nameEn || p.name || '').slice(0, 60),
        amount: Number(p.amount),
        period: String(p.period || '').slice(0, 40),
        periodEn: String(p.periodEn || '').slice(0, 40),
        badge: String(p.badge || '').slice(0, 40),
        badgeEn: String(p.badgeEn || '').slice(0, 40),
      };
    });
}

module.exports = async function handler(req, res) {
  cors(res);
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (!requireAuth(req, res)) return;

  try {
    if (req.method === 'GET') {
      const links = await store.allLinks();
      return res.status(200).json({ links: links, backend: store.backend });
    }

    if (req.method === 'POST') {
      const input = body(req);

      const pricing = PRICING.indexOf(input.pricing) === -1 ? 'fixed' : input.pricing;
      const plans = pricing === 'plans' ? normalizePlans(input.plans) : [];
      const amount = Number(input.amount) || 0;

      if (!String(input.title || '').trim() && !String(input.titleEn || '').trim()) {
        return res.status(400).json({ error: 'A title is required' });
      }
      if (pricing === 'fixed' && amount <= 0) {
        return res.status(400).json({ error: 'A fixed-price link needs an amount above zero' });
      }
      if (pricing === 'plans' && plans.length === 0) {
        return res.status(400).json({ error: 'A plan-based link needs at least one plan with an amount' });
      }

      let slug = slugify(input.slug) || randomId('');
      const existing = await store.getLink(slug);
      if (existing) slug = slug + '-' + randomId('').slice(0, 4);

      const link = {
        slug: slug,
        title: String(input.title || '').slice(0, 120),
        titleEn: String(input.titleEn || '').slice(0, 120),
        description: String(input.description || '').slice(0, 400),
        descriptionEn: String(input.descriptionEn || '').slice(0, 400),
        logoText: String(input.logoText || '').slice(0, 40),
        logoSubText: String(input.logoSubText || '').slice(0, 40),
        brandColor: /^#[0-9a-fA-F]{6}$/.test(input.brandColor || '') ? input.brandColor : '#0EA5E9',
        currency: CURRENCIES.indexOf(input.currency) === -1 ? 'QAR' : input.currency,
        pricing: pricing,
        amount: pricing === 'plans' ? 0 : amount,
        plans: plans,
        collectName: input.collectName !== false,
        collectEmail: input.collectEmail !== false,
        collectPhone: input.collectPhone !== false,
        collectNote: input.collectNote === true,
        successMessage: String(input.successMessage || '').slice(0, 300),
        successMessageEn: String(input.successMessageEn || '').slice(0, 300),
        redirectUrl: /^https?:\/\//.test(input.redirectUrl || '') ? input.redirectUrl : '',
        active: input.active !== false,
        createdAt: new Date().toISOString(),
        views: 0,
        paidCount: 0,
        paidTotal: 0,
      };

      await store.putLink(link);
      return res.status(201).json({ link: link });
    }

    return res.status(405).json({ error: 'Method not allowed' });
  } catch (err) {
    return res.status(500).json({ error: err.message });
  }
};
