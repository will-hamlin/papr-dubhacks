import test, { after, before } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { createServer } from '../server.mjs';

let app;
let receiver;
let base;
let destination;
let received;

const payload = {
  request: { id: 'demo-request-1', text: 'Six monitor arms, budget $900.', createdAt: '2026-10-18T00:00:00.000Z' },
  userConfig: { employeeId: 'EMP-1', customField: { nested: true } },
  companyConfig: { companyId: 'CO-1', purchasePolicy: { preferredVendors: ['Dell'] } },
};

function listen(server) {
  return new Promise(resolve => server.listen(0, '127.0.0.1', () => resolve(`http://127.0.0.1:${server.address().port}`)));
}

function submit(body, extraHeaders = {}) {
  return fetch(`${base}/api/requests`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...extraHeaders }, body: JSON.stringify(body) });
}

before(async () => {
  receiver = http.createServer(async (request, response) => {
    let body = '';
    for await (const chunk of request) body += chunk;
    received = { body: JSON.parse(body), authorization: request.headers.authorization, method: request.method };
    if (request.url === '/reject') {
      response.writeHead(422, { 'Content-Type': 'application/json' });
      return response.end(JSON.stringify({ message: 'Approval policy rejected this request.' }));
    }
    response.writeHead(202, { 'Content-Type': 'application/json' });
    response.end(JSON.stringify({ orderId: 'PO-1042', status: 'queued' }));
  });
  destination = await listen(receiver);
  app = createServer();
  base = await listen(app);
});

after(async () => {
  await Promise.all([app, receiver].map(server => new Promise(resolve => server.close(resolve))));
});

test('dashboard provides two companies with their two requested employee roles', async () => {
  const page = await fetch(base);
  assert.equal(page.status, 200);
  assert.match(await page.text(), /Request order/);
  const profiles = await (await fetch(`${base}/api/profiles`)).json();
  assert.equal(profiles.users.length, 4);
  assert.equal(profiles.companies.length, 2);
  const rolesFor = companyId => profiles.users.filter(user => user.config.companyId === companyId).map(user => user.config.role).sort();
  assert.deepEqual(rolesFor('CO-001'), ['CEO', 'Intern']);
  assert.deepEqual(rolesFor('CO-003'), ['Operations specialist', 'Researcher']);
  assert.equal(profiles.defaultEndpoint, process.env.ORDER_SERVICE_URL || 'https://pbapo.me');
});

test('relay preserves the full payload and forwards the optional bearer token', async () => {
  const response = await submit({ endpoint: `${destination}/orders`, token: 'demo-only-token', payload }, { Origin: base });
  assert.equal(response.status, 200);
  const result = await response.json();
  assert.equal(result.accepted, true);
  assert.equal(result.status, 202);
  assert.deepEqual(received.body, payload);
  assert.equal(received.authorization, 'Bearer demo-only-token');
  assert.equal(received.method, 'POST');
  assert.equal(JSON.parse(result.response).orderId, 'PO-1042');
});

test('upstream rejection is not reported as successful delivery', async () => {
  const response = await submit({ endpoint: `${destination}/reject`, payload });
  const result = await response.json();
  assert.equal(response.status, 502);
  assert.equal(result.accepted, false);
  assert.equal(result.status, 422);
  assert.match(result.response, /Approval policy rejected/);
  assert.equal(received.authorization, undefined);
});

test('missing configurations and empty requests are rejected before forwarding', async () => {
  for (const badPayload of [
    { request: payload.request, userConfig: {} },
    { ...payload, request: { ...payload.request, text: '   ' } },
    { ...payload, companyConfig: [] },
  ]) {
    assert.equal((await submit({ endpoint: destination, payload: badPayload })).status, 400);
  }
});

test('non-HTTP destinations and cross-origin callers are rejected', async () => {
  assert.equal((await submit({ endpoint: 'file:///private', payload })).status, 400);
  assert.equal((await submit({ endpoint: destination, payload }, { Origin: 'https://unrelated.example' })).status, 403);
});

test('unreachable service returns a delivery error', async () => {
  const temporary = http.createServer();
  const unused = await listen(temporary);
  await new Promise(resolve => temporary.close(resolve));
  const response = await submit({ endpoint: unused, payload });
  assert.equal(response.status, 502);
  assert.match((await response.json()).error, /Could not confirm delivery/);
});
