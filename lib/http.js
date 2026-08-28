/** Shared request helpers for the platform's API functions. */

const DEFAULT_PASSCODE = 'demo1234';

function cors(res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PATCH, DELETE, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-Merchant-Key');
}

/**
 * Dashboard gate. A single shared passcode, compared in constant time.
 * Set MERCHANT_PASSCODE in the environment; the default only exists so the demo
 * runs out of the box, and is refused once NODE_ENV is production.
 */
function authorized(req) {
  const configured = process.env.MERCHANT_PASSCODE;
  if (!configured && process.env.NODE_ENV === 'production') return false;
  const expected = configured || DEFAULT_PASSCODE;
  const supplied = String(req.headers['x-merchant-key'] || '');
  if (supplied.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i++) {
    diff |= supplied.charCodeAt(i) ^ expected.charCodeAt(i);
  }
  return diff === 0;
}

function requireAuth(req, res) {
  if (authorized(req)) return true;
  res.status(401).json({ error: 'Unauthorized' });
  return false;
}

/** Vercel parses JSON bodies already; this covers the raw-string case too. */
function body(req) {
  if (!req.body) return {};
  if (typeof req.body === 'string') {
    try { return JSON.parse(req.body); } catch (e) { return {}; }
  }
  return req.body;
}

function slugify(input) {
  return String(input || '')
    .toLowerCase()
    .replace(/[^a-z0-9؀-ۿ]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40);
}

function randomId(prefix) {
  const chars = 'abcdefghijkmnpqrstuvwxyz23456789';
  let out = '';
  for (let i = 0; i < 10; i++) {
    out += chars[Math.floor(Math.random() * chars.length)];
  }
  return prefix ? prefix + '_' + out : out;
}

module.exports = { cors, authorized, requireAuth, body, slugify, randomId };
