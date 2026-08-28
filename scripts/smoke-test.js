/**
 * End-to-end smoke test against the dev server: sign in, list links, create
 * one, run a successful and a declined payment through it, then check the
 * dashboard sees both. Run with `npm test` (starts its own server).
 */

const { spawn } = require('child_process');

const PORT = 3999;
const BASE = 'http://localhost:' + PORT;
const KEY = 'demo1234';

let failures = 0;

function check(label, condition, detail) {
  if (condition) {
    console.log('  ok   ' + label);
  } else {
    failures++;
    console.log('  FAIL ' + label + (detail ? '  → ' + JSON.stringify(detail) : ''));
  }
}

async function call(path, options) {
  const opts = options || {};
  opts.headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
  const res = await fetch(BASE + path, opts);
  const body = await res.json().catch(function () { return {}; });
  return { status: res.status, body: body };
}

const auth = { 'X-Merchant-Key': KEY };

async function run() {
  console.log('\nAuth');
  const noKey = await call('/api/links');
  check('rejects a request with no passcode', noKey.status === 401, noKey.body);
  const wrongKey = await call('/api/links', { headers: { 'X-Merchant-Key': 'nope' } });
  check('rejects a wrong passcode', wrongKey.status === 401, wrongKey.body);

  console.log('\nLinks');
  const list = await call('/api/links', { headers: auth });
  check('lists seeded links', list.status === 200 && list.body.links.length === 3, list.body);
  check('seeds the consultation link', list.body.links.some(function (l) { return l.slug === 'consultation'; }));

  const created = await call('/api/links', {
    method: 'POST',
    headers: auth,
    body: JSON.stringify({
      title: 'فحص دوري', titleEn: 'Routine check-up', slug: 'checkup',
      pricing: 'fixed', amount: 120, currency: 'QAR', collectNote: true,
    }),
  });
  check('creates a fixed-price link', created.status === 201 && created.body.link.slug === 'checkup', created.body);

  const badLink = await call('/api/links', {
    method: 'POST', headers: auth,
    body: JSON.stringify({ title: 'No amount', pricing: 'fixed', amount: 0 }),
  });
  check('refuses a fixed link with no amount', badLink.status === 400, badLink.body);

  console.log('\nPublic checkout payload');
  const pub = await call('/api/link?slug=checkup');
  check('serves the link without a passcode', pub.status === 200, pub.body);
  check('hides merchant-only counters', pub.body.link.paidTotal === undefined, pub.body.link);
  const missing = await call('/api/link?slug=does-not-exist');
  check('404s an unknown slug', missing.status === 404);

  console.log('\nPayments');
  const okPay = await call('/api/checkout', {
    method: 'POST',
    body: JSON.stringify({
      slug: 'checkup', method: 'card', cardNumber: '4242 4242 4242 4242',
      name: 'Sara Ali', email: 'sara@example.com', phone: '33123456', phoneCode: '+974',
    }),
  });
  check('captures a good card', okPay.status === 200 && okPay.body.status === 'CAPTURED', okPay.body);
  check('charges the link amount', okPay.body.amount === 120, okPay.body);

  const declined = await call('/api/checkout', {
    method: 'POST',
    body: JSON.stringify({
      slug: 'checkup', method: 'card', cardNumber: '4000 0000 0000 0002',
      name: 'Sara Ali', email: 'sara@example.com', phone: '33123456', phoneCode: '+974',
    }),
  });
  check('declines the decline-test card', declined.body.status === 'DECLINED', declined.body);
  check('reports the decline reason', declined.body.reason === 'DO_NOT_HONOUR', declined.body);

  const badEmail = await call('/api/checkout', {
    method: 'POST',
    body: JSON.stringify({ slug: 'checkup', method: 'card', cardNumber: '4242424242424242',
      name: 'Sara', email: 'not-an-email', phone: '33123456' }),
  });
  check('rejects an invalid email', badEmail.status === 400, badEmail.body);

  const planPay = await call('/api/checkout', {
    method: 'POST',
    body: JSON.stringify({
      slug: 'consultation', method: 'applepay', planId: 'followup',
      name: 'Khalid', email: 'k@example.com', phone: '55123456', phoneCode: '+974',
    }),
  });
  check('prices a plan from the plan id', planPay.body.amount === 150, planPay.body);
  check('captures a wallet payment with no card', planPay.body.status === 'CAPTURED', planPay.body);

  const noPlan = await call('/api/checkout', {
    method: 'POST',
    body: JSON.stringify({ slug: 'consultation', method: 'applepay', planId: 'ghost',
      name: 'Khalid', email: 'k@example.com', phone: '55123456' }),
  });
  check('refuses an unknown plan id', noPlan.status === 400, noPlan.body);

  console.log('\nDashboard reporting');
  const tx = await call('/api/payments', { headers: auth });
  // Validation failures are rejected before a record is written, so only the
  // three authorised attempts appear: two captures and one decline.
  check('records only authorised attempts', tx.body.summary.count === 3, tx.body.summary);
  check('counts only captured ones in the total', tx.body.summary.capturedCount === 2, tx.body.summary);
  check('totals captured amounts per currency', tx.body.summary.totals.QAR === 270, tx.body.summary);

  const afterPay = await call('/api/links', { headers: auth });
  const checkup = afterPay.body.links.find(function (l) { return l.slug === 'checkup'; });
  check('rolls the capture into the link total', checkup.paidTotal === 120 && checkup.paidCount === 1, checkup);
  check('counts the public page view', checkup.views === 1, checkup);

  console.log('\nDeactivation');
  await call('/api/link?slug=checkup', { method: 'PATCH', headers: auth, body: JSON.stringify({ active: false }) });
  const gone = await call('/api/link?slug=checkup');
  check('a paused link stops serving publicly', gone.status === 410, gone.body);
  const blocked = await call('/api/checkout', {
    method: 'POST',
    body: JSON.stringify({ slug: 'checkup', method: 'card', cardNumber: '4242424242424242',
      name: 'A', email: 'a@b.co', phone: '33123456' }),
  });
  check('a paused link refuses payment', blocked.status === 410, blocked.body);

  const removed = await call('/api/link?slug=checkup', { method: 'DELETE', headers: auth });
  check('deletes a link', removed.status === 200, removed.body);
}

const server = spawn(process.execPath, [__dirname + '/dev-server.js'], {
  env: Object.assign({}, process.env, { PORT: String(PORT), NODE_ENV: 'test' }),
  stdio: ['ignore', 'ignore', 'inherit'],
});

async function waitForServer() {
  for (let i = 0; i < 40; i++) {
    try {
      await fetch(BASE + '/api/link?slug=consultation');
      return true;
    } catch (e) {
      await new Promise(function (r) { setTimeout(r, 100); });
    }
  }
  return false;
}

(async function () {
  const up = await waitForServer();
  if (!up) {
    console.error('dev server did not start');
    server.kill();
    process.exit(1);
  }
  try {
    await run();
  } catch (err) {
    failures++;
    console.error('\nthrew: ' + err.stack);
  }
  server.kill();
  console.log('\n' + (failures ? failures + ' failing check(s)' : 'all checks passed'));
  process.exit(failures ? 1 : 0);
})();
