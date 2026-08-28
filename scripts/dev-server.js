/**
 * Local stand-in for Vercel: serves the static pages and dispatches /api/*
 * to the handler files with a request/response shaped the way the platform
 * expects. Run with `npm run dev`, then open http://localhost:3000.
 */

const http = require('http');
const fs = require('fs');
const path = require('path');
const { URL } = require('url');

const ROOT = path.join(__dirname, '..');
const PORT = Number(process.env.PORT) || 3000;

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
};

function readBody(req) {
  return new Promise(function (resolve) {
    let raw = '';
    req.on('data', function (c) { raw += c; });
    req.on('end', function () {
      if (!raw) return resolve({});
      try { resolve(JSON.parse(raw)); } catch (e) { resolve({}); }
    });
  });
}

function decorate(res) {
  res.status = function (code) { res.statusCode = code; return res; };
  res.json = function (payload) {
    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    res.end(JSON.stringify(payload));
    return res;
  };
  return res;
}

function serveFile(res, filePath) {
  fs.readFile(filePath, function (err, data) {
    if (err) {
      res.statusCode = 404;
      return res.end('Not found');
    }
    res.setHeader('Content-Type', TYPES[path.extname(filePath)] || 'application/octet-stream');
    res.end(data);
  });
}

const server = http.createServer(async function (req, res) {
  const url = new URL(req.url, 'http://localhost');
  const pathname = decodeURIComponent(url.pathname);
  decorate(res);

  if (pathname.startsWith('/api/')) {
    const name = pathname.replace('/api/', '').replace(/\/$/, '');
    const file = path.join(ROOT, 'api', name + '.js');
    if (!fs.existsSync(file)) return res.status(404).json({ error: 'No such function: ' + name });

    req.query = Object.fromEntries(url.searchParams.entries());
    req.body = await readBody(req);

    // Re-require each time so edits land without a restart.
    delete require.cache[require.resolve(file)];
    try {
      await require(file)(req, res);
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
    return;
  }

  // Mirror vercel.json's rewrites.
  if (pathname === '/dashboard') return serveFile(res, path.join(ROOT, 'dashboard.html'));
  if (pathname === '/eilaji') return serveFile(res, path.join(ROOT, 'eilaji.html'));
  if (pathname.startsWith('/p/')) return serveFile(res, path.join(ROOT, 'pay.html'));
  if (pathname === '/') return serveFile(res, path.join(ROOT, 'index.html'));

  const target = path.normalize(path.join(ROOT, pathname));
  if (!target.startsWith(ROOT)) return res.status(403).end('Forbidden');
  serveFile(res, target);
});

server.listen(PORT, function () {
  console.log('Payment-link dev server on http://localhost:' + PORT);
});
