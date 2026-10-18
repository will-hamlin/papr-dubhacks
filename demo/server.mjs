import http from 'node:http';
import { readFile, readdir } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';

const root = dirname(fileURLToPath(import.meta.url));
const assets = new Map([
  ['/', ['index.html', 'text/html; charset=utf-8']],
  ['/app.js', ['app.js', 'text/javascript; charset=utf-8']],
  ['/styles.css', ['styles.css', 'text/css; charset=utf-8']],
  ['/favicon.svg', ['favicon.svg', 'image/svg+xml']],
  ['/admin', ['admin.html', 'text/html; charset=utf-8']],
  ['/admin/', ['admin.html', 'text/html; charset=utf-8']],
  ['/admin.js', ['admin.js', 'text/javascript; charset=utf-8']],
  ['/admin-model.js', ['admin-model.js', 'text/javascript; charset=utf-8']],
  ['/admin.css', ['admin.css', 'text/css; charset=utf-8']],
]);

function json(response, status, data) {
  response.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
  response.end(JSON.stringify(data));
}

async function readBody(request) {
  let text = '';
  for await (const chunk of request) {
    text += chunk;
    if (Buffer.byteLength(text) > 256 * 1024) {
      throw new Error('The request is too large. Keep it under 256 KB.');
    }
  }
  return JSON.parse(text);
}

const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);

async function boundedReply(upstream, limit) {
  const chunks = [];
  let size = 0;
  for await (const chunk of upstream.body || []) {
    size += chunk.length;
    if (size > limit) throw new Error('The service response exceeds the demo response limit.');
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString('utf8');
}

async function loadProfiles(kind) {
  const directory = join(root, 'configs', kind);
  const files = (await readdir(directory)).filter(file => file.endsWith('.json')).sort();
  return Promise.all(files.map(async file => {
    const config = JSON.parse(await readFile(join(directory, file), 'utf8'));
    return { id: file.replace('.json', ''), label: config.name, config };
  }));
}

export function createServer() {
  // Local demo capabilities never accept a polling destination or token from the browser.
  const tracked = new Map();
  return http.createServer(async (request, response) => {
    try {
      const pathname = new URL(request.url, 'http://localhost').pathname;
      if (request.method === 'POST' && pathname === '/api/request-status') {
        if (request.headers.origin && request.headers.origin !== `http://${request.headers.host}`) {
          return json(response, 403, { error: 'This request must come from the local dashboard.' });
        }
        if (!request.headers['content-type']?.startsWith('application/json')) return json(response, 415, { error: 'Send application/json.' });
        let body;
        try { body = await readBody(request); } catch { return json(response, 400, { error: 'Invalid tracking request.' }); }
        if (!isObject(body) || Object.keys(body).length !== 1 || typeof body.trackingId !== 'string') {
          return json(response, 400, { error: 'Send only the trackingId returned for a submitted request.' });
        }
        const entry = tracked.get(body.trackingId);
        if (!entry || entry.expires <= Date.now()) {
          tracked.delete(body.trackingId);
          return json(response, 410, { error: 'Tracking expired or the demo server restarted. The last saved result remains available; do not resubmit to refresh it.' });
        }
        try {
          const upstream = await fetch(entry.url, {
            headers: { Accept: 'application/json', Authorization: `Bearer ${entry.token}` },
            signal: AbortSignal.timeout(10000), redirect: 'error',
          });
          if (!upstream.ok) {
            const expired = [401, 403].includes(upstream.status);
            if (expired) tracked.delete(body.trackingId);
            return json(response, expired ? 410 : 502, { error: expired ? 'Request access expired. The last saved result remains available.' : 'Status temporarily unavailable. The last saved result remains available; try refresh again.' });
          }
          const status = JSON.parse(await boundedReply(upstream, 256 * 1024));
          if (!isObject(status) || status.order_id !== entry.orderId || typeof status.status !== 'string') throw new Error('Invalid order status');
          return json(response, 200, { order_id: status.order_id, status: status.status, result: status.result });
        } catch {
          return json(response, 502, { error: 'Status could not be retrieved. The last saved result remains available; try refresh again.' });
        }
      }
      if (request.method === 'GET' && pathname === '/api/admin/demo-requests') {
        const fixtures = JSON.parse(await readFile(join(root, 'fixtures', 'finance-requests.json'), 'utf8'));
        return json(response, 200, fixtures);
      }
      if (request.method === 'GET' && pathname === '/api/profiles') {
        const [users, companies] = await Promise.all([loadProfiles('users'), loadProfiles('companies')]);
        return json(response, 200, {
          users,
          companies,
          defaultEndpoint: process.env.ORDER_SERVICE_URL || 'http://127.0.0.1:8000/orders',
          defaultToken: process.env.ORDER_SERVICE_TOKEN || 'dev-only-token',
        });
      }

      if (request.method === 'POST' && pathname === '/api/requests') {
        // The relay is local-only and accepts requests from this dashboard's origin.
        const origin = request.headers.origin;
        if (origin && origin !== `http://${request.headers.host}`) {
          return json(response, 403, { error: 'This request must come from the local dashboard.' });
        }
        if (!request.headers['content-type']?.startsWith('application/json')) {
          return json(response, 415, { error: 'Send application/json.' });
        }

        let body;
        let destination;
        try {
          body = await readBody(request);
          destination = new URL(body.endpoint);
          if (!['http:', 'https:'].includes(destination.protocol) || destination.username || destination.password) {
            throw new Error('Enter an HTTP or HTTPS service URL without embedded credentials.');
          }
          const payload = body.payload;
          if (!isObject(payload) || !isObject(payload.request) ||
              typeof payload.request.text !== 'string' || !payload.request.text.trim() ||
              typeof payload.request.id !== 'string' || typeof payload.request.createdAt !== 'string' ||
              !isObject(payload.userConfig) || !isObject(payload.companyConfig)) {
            throw new Error('Include a request and both configuration objects.');
          }
          if (body.token !== undefined && typeof body.token !== 'string') {
            throw new Error('The bearer token must be text.');
          }
        } catch (error) {
          return json(response, 400, { error: error.message });
        }

        try {
          const headers = { 'Content-Type': 'application/json', Accept: 'application/json' };
          if (body.token) headers.Authorization = `Bearer ${body.token}`;
          const upstream = await fetch(destination, {
            method: 'POST', headers, body: JSON.stringify(body.payload),
            signal: AbortSignal.timeout(20000), redirect: 'error',
          });
          let reply = await boundedReply(upstream, 16000);
          let order;
          let trackingId;
          try {
            const parsed = JSON.parse(reply);
            if (isObject(parsed)) {
              const accessToken = parsed.request_token;
              delete parsed.request_token;
              reply = JSON.stringify(parsed);
              if (typeof parsed.order_id === 'string' && /^[a-zA-Z0-9_-]{1,128}$/.test(parsed.order_id)) {
                order = parsed;
                if (upstream.ok && parsed.ok === true && typeof accessToken === 'string' && accessToken.length <= 4000 &&
                    destination.pathname.replace(/\/$/, '').endsWith('/orders') && !destination.search && !destination.hash) {
                  for (const [id, entry] of tracked) if (entry.expires <= Date.now()) tracked.delete(id);
                  if (tracked.size >= 1000) tracked.delete(tracked.keys().next().value);
                  trackingId = randomUUID();
                  const statusUrl = new URL(destination);
                  statusUrl.pathname = `${destination.pathname.replace(/\/$/, '')}/${encodeURIComponent(parsed.order_id)}`;
                  tracked.set(trackingId, { url: statusUrl.href, orderId: parsed.order_id, token: accessToken, expires: Date.now() + 86400000 });
                }
              }
            }
          } catch { /* Non-JSON upstream receipts remain a bounded text preview. */ }
          return json(response, upstream.ok ? 200 : 502, {
            accepted: upstream.ok, status: upstream.status, response: reply,
            ...(order && { order }), ...(trackingId && { trackingId }),
            ...(!upstream.ok && { error: `The service returned HTTP ${upstream.status}. Review the response before retrying.` }),
          });
        } catch (error) {
          const timeout = error.name === 'TimeoutError' || error.name === 'AbortError';
          return json(response, 502, { error: timeout
            ? 'The service did not respond within 20 seconds. It may have received the request; check before retrying.'
            : 'Could not confirm delivery. Check the service URL and whether it is running before retrying.' });
        }
      }

      const asset = assets.get(pathname);
      if (request.method === 'GET' && asset) {
        response.writeHead(200, { 'Content-Type': asset[1], 'Cache-Control': 'no-cache', 'X-Content-Type-Options': 'nosniff' });
        return response.end(await readFile(join(root, 'public', asset[0])));
      }
      json(response, 404, { error: 'Not found' });
    } catch {
      json(response, 500, { error: 'The dashboard could not complete this action.' });
    }
  });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const port = Number(process.env.PORT || 3000);
  createServer().listen(port, '127.0.0.1', () => console.log(`Enterprise demo: http://127.0.0.1:${port}`));
}
