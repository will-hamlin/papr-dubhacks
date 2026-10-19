import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { readFile, readdir } from 'node:fs/promises';
import { JSDOM } from 'jsdom';
import { createServer } from '../server.mjs';

const html = await readFile(new URL('../public/index.html', import.meta.url), 'utf8');
const script = await readFile(new URL('../public/app.js', import.meta.url), 'utf8');
async function profiles(kind) {
  const directory = new URL(`../configs/${kind}/`, import.meta.url);
  return Promise.all((await readdir(directory)).filter(file => file.endsWith('.json')).sort().map(async file => {
    const config = JSON.parse(await readFile(new URL(file, directory), 'utf8'));
    return { id: file.replace('.json', ''), label: config.name, config };
  }));
}
const seeds = { users: await profiles('users'), companies: await profiles('companies'), defaultEndpoint: 'http://127.0.0.1:8000/orders' };
const payload = { request: { id: 'request-test', text: 'USB-C hub for the office.', createdAt: '2026-10-18T10:00:00Z' }, userConfig: seeds.users[0].config, companyConfig: seeds.companies.find(item => item.id === 'northstar').config };
const accepted = { accepted: true, status: 200, trackingId: 'opaque-local-handle', response: '{"ok":true,"order_id":"order-1"}', order: { ok: true, order_id: 'order-1', decision: 'accepted', main_service: { order_id: 'order-1', status: 'queued' } } };
const complete = { order_id: 'order-1', status: 'verification_complete', result: { engine: { demo: true }, verification: { candidates: [{ candidate_id: 'listing-1', claims_status: 'supported', requirements_status: 'contradicted', evidence: { basis: 'demo_fixture' }, requirement_checks: [{ field: 'max_total_cents', expected: 10000, observed: 12000, status: 'contradicted' }] }] } } };
const tick = () => new Promise(setImmediate);

async function openApp(receipt = accepted, statuses = []) {
  const dom = new JSDOM(html, { url: 'http://127.0.0.1:3000', runScripts: 'outside-only' });
  const { window } = dom;
  window.structuredClone = structuredClone;
  window.AbortSignal = AbortSignal;
  window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  window.HTMLDialogElement.prototype.close = function () { this.open = false; };
  const polls = [];
  window.fetch = async (url, options) => {
    if (url === '/api/profiles') return Response.json(seeds);
    if (url === '/api/requests') return Response.json(receipt, { status: receipt.accepted ? 200 : 502 });
    assert.equal(url, '/api/request-status');
    polls.push(JSON.parse(options.body));
    const next = statuses.shift() || { body: complete };
    return Response.json(next.body, { status: next.status || 200 });
  };
  window.eval(script); await tick();
  const query = selector => window.document.querySelector(selector);
  query('#request-order').click(); query('#request-text').value = payload.request.text;
  query('#request-form').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
  await tick(); await tick();
  return { window, query, polls, stored: () => JSON.parse(window.localStorage.getItem('generic-enterprise-v1')) };
}

test('employee request progresses from awaiting listings to condition-level evidence without implying approval', async t => {
  const app = await openApp(accepted, [{ body: { order_id: 'order-1', status: 'awaiting_candidates', result: {} } }, { body: complete }]);
  t.after(() => app.window.close());
  assert.equal(app.query('#details-dialog').open, true);
  assert.match(app.query('#request-history').textContent, /Awaiting listings/);
  assert.match(app.query('#verification-summary').textContent, /waiting for product listings/);
  app.query('#refresh-request').click(); await tick();
  assert.match(app.query('#request-history').textContent, /Evidence reviewed/);
  assert.match(app.query('#verification-summary').textContent, /Simulated supplier evidence/);
  assert.match(app.query('#verification-summary').textContent, /Total cost: contradicted/);
  assert.match(app.query('#verification-summary').textContent, /\$100\.00.*\$120\.00/);
  assert.match(app.query('#receipt-description').textContent, /does not authorize or place a purchase/);
  assert.equal(app.stored().history[0].progress.status, 'verification_complete');
  assert.deepEqual(app.polls, [{ trackingId: 'opaque-local-handle' }, { trackingId: 'opaque-local-handle' }]);
});

test('denied requests are saved with the proxy reason and do not request status without access', async t => {
  const order = { ok: false, order_id: 'denied-1', decision: 'over_budget', reason: 'Requested amount exceeds employee limit.' };
  const app = await openApp({ accepted: false, status: 403, order, response: JSON.stringify(order) });
  t.after(() => app.window.close());
  assert.equal(app.stored().history.length, 1);
  assert.match(app.query('#request-history').textContent, /Denied/);
  assert.match(app.query('#verification-summary').textContent, /exceeds employee limit/);
  assert.equal(app.query('#refresh-request').disabled, true);
  assert.equal(app.polls.length, 0);
});

test('formal results distinguish proof, rejection and missing evidence and expose audit bindings', async t => {
  const result = structuredClone(complete);
  result.result.specs = { item: 'USB-C charger', quantity: 1, condition: 'new', english: ['power ≥ 65 W (required)'] };
  result.result.limits = { max_total_cents: 4000 };
  result.result.verification.candidates = ['proven', 'rejected', 'unknown'].map((status, index) => ({
    ...complete.result.verification.candidates[0], candidate_id: `candidate-${index}`, simulated: true,
    formal_proof: { status, engine: 'agent-purchase-verifier / Z3', reason: `Proof outcome ${status}`,
      requirements_id: 'bound-requirements', receipt_hash: 'receipt-sha', evidence_sha256: 'source-sha',
      missing_fields: status === 'unknown' ? ['power'] : [] },
  }));
  const app = await openApp(accepted, [{ body: result }]);
  t.after(() => app.window.close());
  assert.equal(app.query('.proof-metric.proven strong').textContent, '1');
  assert.equal(app.query('.proof-metric.rejected strong').textContent, '1');
  assert.equal(app.query('.proof-metric.unknown strong').textContent, '1');
  assert.match(app.query('.requirements-card').textContent, /USB-C charger.*\$40\.00/);
  assert.match(app.query('#verification-summary').textContent, /Requirements proven.*Requirements not met.*Evidence incomplete/s);
  assert.match(app.query('.proof-details').textContent, /bound-requirements.*source-sha.*receipt-sha/s);
  assert.equal(app.query('#download-proof').disabled, false);
});

test('backend review is actionable and unsafe approval URLs never become links', async t => {
  const result = { status: 'submitted', result: { engine: { status: 'escalated',
    approval_url: 'http://127.0.0.1:8002/#/requests/review', questions: [{ text: 'Which size?' }] } } };
  const bad = structuredClone(result); bad.result.engine.approval_url = 'javascript:alert(1)';
  const app = await openApp(accepted, [{ body: result }, { body: bad }]);
  t.after(() => app.window.close());
  assert.match(app.query('#request-history').textContent, /Review needed/);
  assert.match(app.query('.review-needed').textContent, /Which size/);
  assert.equal(app.query('.review-needed a').rel, 'noopener noreferrer');
  app.query('#refresh-request').click(); await tick();
  assert.equal(app.query('.review-needed a'), null);
});

test('example requests fill the form without submitting an order', async t => {
  const app = await openApp(); t.after(() => app.window.close());
  app.query('[aria-label="Close details"]').click();
  app.query('#request-order').click();
  const before = app.stored().history.length;
  app.query('[data-example-request]').click();
  assert.equal(app.query('#request-text').value, '65W USB-C charger under $40');
  assert.equal(app.stored().history.length, before);
});

test('polling failures retain the last result, and expired access disables further polling', async t => {
  const app = await openApp(accepted, [{ body: complete }, { status: 502, body: { error: 'Status temporarily unavailable.' } }, { status: 410, body: { error: 'Tracking expired.' } }]);
  t.after(() => app.window.close());
  app.query('#refresh-request').click(); await tick();
  assert.match(app.query('#tracking-note').textContent, /temporarily unavailable/);
  assert.match(app.query('#verification-summary').textContent, /Total cost/);
  assert.equal(app.stored().history[0].progress.status, 'verification_complete');
  app.query('#refresh-request').click(); await tick();
  assert.equal(app.query('#refresh-request').disabled, true);
  assert.equal(app.stored().history[0].trackingExpired, true);
  assert.match(app.query('#verification-summary').textContent, /Total cost/);
});

test('legacy receipts without a status capability remain viewable without automatic requests', async t => {
  const app = await openApp({ accepted: true, status: 202, response: '{"orderId":"old-server"}' });
  t.after(() => app.window.close());
  assert.match(app.query('#request-history').textContent, /Submitted/);
  assert.match(app.query('#tracking-note').textContent, /no status access/);
  assert.equal(app.polls.length, 0);
});

test('evidence details show product names, units and currency while preserving full raw evidence', async t => {
  const report = structuredClone(complete);
  const candidate = report.result.verification.candidates[0];
  candidate.facts = { name: { value: 'Research Laptop' }, sku: { value: 'LAP-32' } };
  candidate.requirement_checks.push(
    { field: 'ram', expected: 32000, unit: 'MB', op: 'ge', observed: { value: 32, unit: 'GB' }, status: 'supported' },
    { field: 'approved_supplier', observed: 'demo-supplier', status: 'supported' },
    { field: 'power', expected: 65, unit: 'W', observed: null, status: 'unverified' });
  const app = await openApp(accepted, [{ body: report }]);
  t.after(() => app.window.close());
  assert.equal(app.query('.candidate-review h3').textContent, 'Research Laptop · LAP-32');
  const summary = app.query('#verification-summary').textContent;
  assert.match(summary, /Listing ID: listing-1/);
  assert.match(summary, /Memory \(RAM\): supportedExpected ≥ 32,000 MB · Observed 32 GB/);
  assert.match(summary, /Approved supplier: supportedObserved demo-supplier/);
  assert.match(summary, /Power: unverifiedExpected 65 W · Observed Unavailable/);
  assert.doesNotMatch(summary, /\{"value"|not supplied/);
  assert.equal(JSON.parse(app.query('#receipt-response').textContent).result.verification.candidates[0].requirement_checks[1].expected, 32000);
});

test('a listing without a product name uses the source slug and keeps its identifier secondary', async t => {
  const report = structuredClone(complete);
  report.result.verification.candidates[0].url = 'https://supplier.example/products/office-laptop';
  const app = await openApp(accepted, [{ body: report }]);
  t.after(() => app.window.close());
  assert.equal(app.query('.candidate-review h3').textContent, 'office laptop');
  assert.match(app.query('#verification-summary').textContent, /Listing ID: listing-1/);
});

test('status relay binds a private access token to the submitted destination and rejects redirects and arbitrary URLs', async () => {
  let statusCode = 200;
  let statusBody = complete;
  const incoming = [];
  const upstream = http.createServer(async (request, response) => {
    for await (const _chunk of request) { /* consume the submitted request */ }
    incoming.push({ url: request.url, method: request.method, authorization: request.headers.authorization });
    if (request.method === 'POST') {
      response.writeHead(200, { 'Content-Type': 'application/json' });
      return response.end(JSON.stringify({ ...accepted.order, request_token: 'private-scoped-capability' }));
    }
    response.writeHead(statusCode, { 'Content-Type': 'application/json', ...(statusCode === 302 && { Location: '/must-not-follow' }) });
    response.end(JSON.stringify(statusBody));
  });
  const app = createServer();
  const listen = server => new Promise(resolve => server.listen(0, '127.0.0.1', () => resolve(`http://127.0.0.1:${server.address().port}`)));
  const destination = await listen(upstream); const base = await listen(app);
  const post = (path, body, origin = base) => fetch(`${base}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json', Origin: origin }, body: JSON.stringify(body) });
  try {
    const receipt = await (await post('/api/requests', { endpoint: `${destination}/orders`, payload })).json();
    assert.equal(typeof receipt.trackingId, 'string');
    assert.doesNotMatch(JSON.stringify(receipt), /private-scoped-capability|request_token/);
    const poll = { trackingId: receipt.trackingId };
    assert.equal((await post('/api/request-status', { ...poll, endpoint: 'http://arbitrary.example/' })).status, 400);
    assert.equal((await post('/api/request-status', poll, 'https://unrelated.example')).status, 403);
    assert.equal((await post('/api/request-status', { trackingId: 'not-issued' })).status, 410);
    assert.equal(incoming.length, 1);
    assert.deepEqual(await (await post('/api/request-status', poll)).json(), complete);
    assert.deepEqual(incoming.at(-1), { url: '/orders/order-1', method: 'GET', authorization: 'Bearer private-scoped-capability' });
    statusCode = 302;
    assert.equal((await post('/api/request-status', poll)).status, 502);
    assert.ok(incoming.every(request => request.url !== '/must-not-follow'));
    statusCode = 200; statusBody = { ...complete, order_id: 'different-order' };
    assert.equal((await post('/api/request-status', poll)).status, 502);
    statusCode = 401;
    assert.equal((await post('/api/request-status', poll)).status, 410);
    const count = incoming.length;
    assert.equal((await post('/api/request-status', poll)).status, 410);
    assert.equal(incoming.length, count);
  } finally { await Promise.all([app, upstream].map(server => new Promise(resolve => server.close(resolve)))); }
});
