/**
 * Storage layer for the payment-link platform.
 *
 * Two backends, picked automatically:
 *   1. Upstash / Vercel KV over REST, when KV_REST_API_URL + KV_REST_API_TOKEN are set.
 *   2. An in-process Map, otherwise. Survives warm invocations only — fine for a demo,
 *      not for anything you care about keeping.
 *
 * Everything is stored as two JSON blobs (links, payments). That is deliberate: at
 * demo scale it keeps the code dependency-free. Swap the read/write pair below for
 * real per-row keys before this ever holds a meaningful number of links.
 */

const LINKS_KEY = 'sadadclone:links';
const PAYMENTS_KEY = 'sadadclone:payments';

const KV_URL = process.env.KV_REST_API_URL;
const KV_TOKEN = process.env.KV_REST_API_TOKEN;
const useKv = Boolean(KV_URL && KV_TOKEN);

function memory() {
  if (!globalThis.__sadadStore) {
    globalThis.__sadadStore = new Map();
  }
  return globalThis.__sadadStore;
}

async function kvGet(key) {
  const res = await fetch(KV_URL + '/get/' + encodeURIComponent(key), {
    headers: { Authorization: 'Bearer ' + KV_TOKEN },
  });
  if (!res.ok) throw new Error('KV read failed: ' + res.status);
  const body = await res.json();
  if (body.result == null) return null;
  return typeof body.result === 'string' ? JSON.parse(body.result) : body.result;
}

async function kvSet(key, value) {
  const res = await fetch(KV_URL + '/set/' + encodeURIComponent(key), {
    method: 'POST',
    headers: {
      Authorization: 'Bearer ' + KV_TOKEN,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(value),
  });
  if (!res.ok) throw new Error('KV write failed: ' + res.status);
}

async function read(key, fallback) {
  if (useKv) {
    const value = await kvGet(key);
    return value == null ? fallback : value;
  }
  const store = memory();
  return store.has(key) ? store.get(key) : fallback;
}

async function write(key, value) {
  if (useKv) return kvSet(key, value);
  memory().set(key, value);
}

// ---------------------------------------------------------------- seed data

function demoLinks() {
  const doctorAr = 'د. عبدالرحمن النملان';
  const doctorEn = 'Dr. Abdulrahman Alnamlan';
  return [
    {
      slug: 'consultation',
      title: 'استشارة طبية — ' + doctorAr,
      titleEn: 'Medical consultation — ' + doctorEn,
      description: 'جلسة استشارية مدتها ٣٠ دقيقة. اختر نوع الاستشارة، أدخل بياناتك، وادفع بأمان.',
      descriptionEn: 'A 30-minute consultation. Pick the consultation type, enter your details, and pay securely.',
      logoText: doctorAr,
      logoSubText: 'CONSULTATION',
      brandColor: '#0EA5E9',
      currency: 'QAR',
      pricing: 'plans',
      amount: 0,
      plans: [
        { id: 'first', name: 'استشارة أولى', nameEn: 'First consultation', amount: 250, period: '٣٠ دقيقة', periodEn: '30 minutes' },
        { id: 'followup', name: 'مراجعة', nameEn: 'Follow-up', amount: 150, period: '٢٠ دقيقة', periodEn: '20 minutes', badge: 'الأكثر حجزاً', badgeEn: 'Most booked' },
        { id: 'package', name: 'باقة ٣ جلسات', nameEn: 'Package of 3 sessions', amount: 600, period: 'صالحة ٣ أشهر', periodEn: 'valid for 3 months', badge: 'وفّر ٢٠٪', badgeEn: 'Save 20%' },
      ],
      collectName: true,
      collectEmail: true,
      collectPhone: true,
      collectNote: true,
      successMessage: 'تم استلام دفعتك. ستصلك رسالة بموعد الاستشارة خلال ٢٤ ساعة.',
      successMessageEn: 'Payment received. You will get your consultation appointment within 24 hours.',
      redirectUrl: '',
      active: true,
      createdAt: '2026-08-10T11:30:00.000Z',
      views: 0,
      paidCount: 0,
      paidTotal: 0,
    },
    {
      slug: 'online-visit',
      title: 'استشارة عن بُعد — ' + doctorAr,
      titleEn: 'Remote consultation — ' + doctorEn,
      description: 'استشارة عبر مكالمة مرئية من أي مكان، بنفس جودة العيادة.',
      descriptionEn: 'A video consultation from anywhere, with the same care as the clinic.',
      logoText: doctorAr,
      logoSubText: 'TELEHEALTH',
      brandColor: '#7C3AED',
      currency: 'QAR',
      pricing: 'fixed',
      amount: 180,
      plans: [],
      collectName: true,
      collectEmail: true,
      collectPhone: true,
      collectNote: true,
      successMessage: 'تم الحجز. سيصلك رابط المكالمة المرئية قبل الموعد بساعة.',
      successMessageEn: 'Booked. Your video call link arrives one hour before the appointment.',
      redirectUrl: '',
      active: true,
      createdAt: '2026-08-18T07:15:00.000Z',
      views: 0,
      paidCount: 0,
      paidTotal: 0,
    },
    {
      slug: 'custom',
      title: 'دفعة مخصصة — ' + doctorAr,
      titleEn: 'Custom payment — ' + doctorEn,
      description: 'ادفع المبلغ المتفق عليه مع العيادة — إجراء، تقرير طبي، أو رسوم إضافية.',
      descriptionEn: 'Pay the amount agreed with the clinic — a procedure, a medical report, or an additional fee.',
      logoText: doctorAr,
      logoSubText: 'CLINIC',
      brandColor: '#059669',
      currency: 'QAR',
      pricing: 'open',
      amount: 100,
      plans: [],
      collectName: true,
      collectEmail: true,
      collectPhone: true,
      collectNote: true,
      successMessage: 'تم استلام دفعتك. يمكنك طلب الإيصال من الاستقبال.',
      successMessageEn: 'Payment received. You can request the receipt from reception.',
      redirectUrl: '',
      active: true,
      createdAt: '2026-08-22T09:40:00.000Z',
      views: 0,
      paidCount: 0,
      paidTotal: 0,
    },
  ];
}

// ------------------------------------------------------------------- links

async function allLinks() {
  return read(LINKS_KEY, null).then(function (links) {
    if (links) return links;
    const seeded = demoLinks();
    return write(LINKS_KEY, seeded).then(function () { return seeded; });
  });
}

async function saveLinks(links) {
  await write(LINKS_KEY, links);
}

async function getLink(slug) {
  const links = await allLinks();
  return links.find(function (l) { return l.slug === slug; }) || null;
}

async function putLink(link) {
  const links = await allLinks();
  const index = links.findIndex(function (l) { return l.slug === link.slug; });
  if (index === -1) links.unshift(link);
  else links[index] = link;
  await saveLinks(links);
  return link;
}

async function deleteLink(slug) {
  const links = await allLinks();
  const next = links.filter(function (l) { return l.slug !== slug; });
  if (next.length === links.length) return false;
  await saveLinks(next);
  return true;
}

// ---------------------------------------------------------------- payments

async function allPayments() {
  return read(PAYMENTS_KEY, []);
}

async function addPayment(payment) {
  const payments = await allPayments();
  payments.unshift(payment);
  // Keep the demo store bounded.
  await write(PAYMENTS_KEY, payments.slice(0, 500));
  return payment;
}

async function getPayment(id) {
  const payments = await allPayments();
  return payments.find(function (p) { return p.id === id; }) || null;
}

module.exports = {
  allLinks,
  getLink,
  putLink,
  deleteLink,
  allPayments,
  addPayment,
  getPayment,
  backend: useKv ? 'kv' : 'memory',
};
