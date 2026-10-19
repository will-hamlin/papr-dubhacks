import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { JSDOM } from 'jsdom';
import * as model from '../public/admin-model.js';
import { createServer } from '../server.mjs';

const fixtures = JSON.parse(await readFile(new URL('../fixtures/finance-requests.json', import.meta.url), 'utf8'));
const html = await readFile(new URL('../public/admin.html', import.meta.url), 'utf8');
const script = (await readFile(new URL('../public/admin.js', import.meta.url), 'utf8'))
  .replace(/^import .*?;\r?\n/, 'const { statusLabels, proofLabels, money, dateLabel, filterRequests, summarizeRequests, exportRecords } = window.adminModel;\n');

async function openAdmin(data = fixtures, ok = true) {
  const dom = new JSDOM(html, { url: 'http://127.0.0.1:3010/admin', runScripts: 'outside-only' });
  const { window } = dom;
  window.adminModel = model;
  window.fetch = async url => {
    assert.equal(url, '/api/admin/demo-requests');
    return Response.json(data, { status: ok ? 200 : 503 });
  };
  window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  window.HTMLDialogElement.prototype.close = function () { this.open = false; this.dispatchEvent(new window.Event('close')); };
  window.eval(script);
  await new Promise(setImmediate);
  const query = selector => window.document.querySelector(selector);
  const change = (selector, value, event = 'change') => {
    query(selector).value = value;
    query(selector).dispatchEvent(new window.Event(event, { bubbles: true }));
  };
  return { dom, window, query, change };
}

test('demo records maintain separate authorization, evidence, and fulfillment states', () => {
  assert.equal(fixtures.demo, true);
  assert.equal(new Set(fixtures.requests.map(request => request.id)).size, fixtures.requests.length);
  assert.deepEqual(new Set(fixtures.requests.map(request => request.status)), new Set(Object.keys(model.statusLabels)));
  for (const request of fixtures.requests) {
    assert.equal(request.proof.formalProof, false);
    assert.equal(request.proof.kind, 'simulated_listing_checks');
    assert.equal(request.events.some(event => event.label === 'Order fulfilled · simulated'), request.status === 'fulfilled');
    if (request.status === 'fulfilled') {
      assert.equal(request.proof.status, 'supported');
      assert.equal(request.actualCents, request.requestedCents);
    } else assert.equal(request.actualCents, null);
    if (request.status === 'denied') {
      assert.equal(request.proof.status, 'not_run');
      assert.equal(request.proof.checks.length, 0);
      assert.equal(request.proof.source, null);
    }
    if (request.proof.source) assert.match(new URL(request.proof.source).hostname, /\.example$/);
    const times = request.events.map(event => event.at);
    assert.deepEqual(times, [...times].sort());
    assert.ok(times.every(time => time <= fixtures.snapshot));
  }
});

test('compound filters and ordering never mutate the fixture database', () => {
  const before = JSON.stringify(fixtures);
  const result = model.filterRequests(fixtures.requests, { query: '  SUPPLY  ', company: 'Meridian Research', status: 'fulfilled', proof: 'supported', sort: 'amount' });
  assert.ok(result.length > 1);
  assert.ok(result.every(request => request.company === 'Meridian Research' && request.status === 'fulfilled' && request.proof.status === 'supported'));
  assert.deepEqual(result.map(request => request.requestedCents), result.map(request => request.requestedCents).sort((a, b) => b - a));
  assert.equal(JSON.stringify(fixtures), before);
  assert.equal(model.filterRequests(fixtures.requests, { query: 'no-such-request' }).length, 0);
});

test('spend excludes ready, pending, denied, and failed purchases', () => {
  const summary = model.summarizeRequests(fixtures.requests);
  assert.equal(summary.fulfilled, 9);
  assert.equal(summary.open, 4);
  assert.equal(summary.exceptions, 5);
  assert.equal(summary.spend, 602400);
  assert.equal(model.summarizeRequests(model.filterRequests(fixtures.requests, { status: 'verified' })).spend, 0);
  assert.deepEqual(model.summarizeRequests([]), { total: 0, fulfilled: 0, spend: 0, open: 0, exceptions: 0 });
});

test('filters, empty-state recovery, and evidence detail work through UI events', async () => {
  const { dom, query, change } = await openAdmin();
  try {
    assert.equal(query('#rows').children.length, fixtures.requests.length);
    change('#company', 'Meridian Research');
    change('#status', 'verification_failed');
    assert.equal(query('#rows').children.length, 2);
    query('[data-request="PAPR-2216"]').click();
    assert.equal(query('#detail').open, true);
    assert.match(query('#detail-content').textContent, /15,000 rpm/);
    assert.match(query('#detail-content').textContent, /12,000 rpm/);
    assert.match(query('#detail-content').textContent, /Contradicted/);
    assert.match(query('#detail-content').textContent, /No purchase recorded/);
    assert.match(query('#detail-content').textContent, /not cryptographic certificates or formal solver proofs/);
    query('#close-detail').click();
    assert.equal(query('#detail').open, false);
    change('#search', 'does not exist', 'input');
    assert.equal(query('#empty').hidden, false);
    assert.equal(query('#rows').children.length, 0);
    query('#reset').click();
    assert.equal(query('#empty').hidden, true);
    assert.equal(query('#rows').children.length, fixtures.requests.length);
    change('#proof', 'not_run');
    assert.equal(query('#rows').children.length, 2);
    query('[data-request="PAPR-2214"]').click();
    assert.match(query('#detail-content').textContent, /No proof was initiated because authorization was denied/);
  } finally { dom.window.close(); }
});

test('rendered record content is escaped in the table and review panel', async () => {
  const modified = structuredClone(fixtures);
  modified.requests[0].title = '<img src=x onerror="window.injected=true">';
  modified.requests[0].proof.checks[0].observed = '<script>window.injected=true</script>';
  const { dom, query } = await openAdmin(modified);
  try {
    assert.equal(query('#rows img'), null);
    query('[data-request="PAPR-2218"]').click();
    assert.equal(query('#detail-content img'), null);
    assert.equal(query('#detail-content script'), null);
    assert.match(query('#detail-content').textContent, /<script>/);
  } finally { dom.window.close(); }
});

test('export contains only filtered records and keeps fictional provenance', () => {
  const selected = model.filterRequests(fixtures.requests, { status: 'denied' });
  const exported = JSON.parse(model.exportRecords(selected, fixtures.snapshot));
  assert.equal(exported.demo, true);
  assert.match(exported.notice, /no formal proofs or real purchases/);
  assert.equal(exported.requests.length, 2);
  assert.ok(exported.requests.every(request => request.status === 'denied'));
  assert.ok(exported.requests.every(request => request.events.length > 0));
});

test('unavailable ledger shows an actionable error and disables export', async () => {
  const { dom, query } = await openAdmin({}, false);
  try {
    assert.equal(query('#load-error').hidden, false);
    assert.match(query('#load-error').textContent, /Reload this page/);
    assert.equal(query('#export').disabled, true);
    assert.equal(query('#snapshot').textContent, 'Demo ledger unavailable');
  } finally { dom.window.close(); }
});

test('admin fixture endpoint is read-only and employee demo is preserved', async () => {
  const server = createServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    const page = await fetch(`${base}/admin`);
    assert.equal(page.status, 200);
    assert.match(await page.text(), /Finance ledger/);
    assert.match(await (await fetch(`${base}/`)).text(), /Request order/);
    const records = await fetch(`${base}/api/admin/demo-requests`);
    assert.equal(records.headers.get('cache-control'), 'no-store');
    assert.deepEqual(await records.json(), fixtures);
    assert.equal((await fetch(`${base}/api/admin/demo-requests`, { method: 'POST', body: '{}' })).status, 404);
    assert.equal((await fetch(`${base}/admin-model.js`)).status, 200);
  } finally { await new Promise(resolve => server.close(resolve)); }
});
