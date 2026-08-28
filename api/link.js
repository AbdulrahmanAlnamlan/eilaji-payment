/** GET    /api/link?slug=x  → public payload for the hosted checkout page
 *  PATCH  /api/link?slug=x  → update a link (authorized)
 *  DELETE /api/link?slug=x  → remove a link (authorized) */

const store = require('../lib/store');
const { cors, authorized, body } = require('../lib/http');

/** The checkout page gets no counters and no merchant-only fields. */
function publicView(link) {
  return {
    slug: link.slug,
    title: link.title,
    titleEn: link.titleEn,
    description: link.description,
    descriptionEn: link.descriptionEn,
    logoText: link.logoText,
    logoSubText: link.logoSubText,
    brandColor: link.brandColor,
    currency: link.currency,
    pricing: link.pricing,
    amount: link.amount,
    plans: link.plans,
    collectName: link.collectName,
    collectEmail: link.collectEmail,
    collectPhone: link.collectPhone,
    collectNote: link.collectNote,
    successMessage: link.successMessage,
    successMessageEn: link.successMessageEn,
    redirectUrl: link.redirectUrl,
  };
}

const EDITABLE = [
  'title', 'titleEn', 'description', 'descriptionEn', 'logoText', 'logoSubText',
  'brandColor', 'currency', 'pricing', 'amount', 'plans', 'collectName',
  'collectEmail', 'collectPhone', 'collectNote', 'successMessage',
  'successMessageEn', 'redirectUrl', 'active',
];

module.exports = async function handler(req, res) {
  cors(res);
  if (req.method === 'OPTIONS') return res.status(200).end();

  const slug = String((req.query && req.query.slug) || '').trim();
  if (!slug) return res.status(400).json({ error: 'Missing slug' });

  try {
    const link = await store.getLink(slug);
    if (!link) return res.status(404).json({ error: 'Link not found' });

    if (req.method === 'GET') {
      if (authorized(req)) return res.status(200).json({ link: link });
      if (!link.active) return res.status(410).json({ error: 'This payment link is no longer active' });
      // Counting a view here is good enough for a demo; a real one would
      // dedupe by visitor and write asynchronously.
      link.views = (link.views || 0) + 1;
      await store.putLink(link);
      return res.status(200).json({ link: publicView(link) });
    }

    if (req.method === 'PATCH') {
      if (!authorized(req)) return res.status(401).json({ error: 'Unauthorized' });
      const input = body(req);
      EDITABLE.forEach(function (key) {
        if (Object.prototype.hasOwnProperty.call(input, key)) link[key] = input[key];
      });
      if (!/^#[0-9a-fA-F]{6}$/.test(link.brandColor || '')) link.brandColor = '#0EA5E9';
      await store.putLink(link);
      return res.status(200).json({ link: link });
    }

    if (req.method === 'DELETE') {
      if (!authorized(req)) return res.status(401).json({ error: 'Unauthorized' });
      await store.deleteLink(slug);
      return res.status(200).json({ deleted: slug });
    }

    return res.status(405).json({ error: 'Method not allowed' });
  } catch (err) {
    return res.status(500).json({ error: err.message });
  }
};
