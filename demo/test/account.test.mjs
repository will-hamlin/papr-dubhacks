import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { JSDOM } from 'jsdom';

const html = await readFile(new URL('../public/index.html', import.meta.url), 'utf8');
const script = await readFile(new URL('../public/app.js', import.meta.url), 'utf8');
const storageKey = 'generic-enterprise-v1';

async function profiles(kind) {
  const directory = new URL(`../configs/${kind}/`, import.meta.url);
  const files = (await readdir(directory)).filter(file => file.endsWith('.json')).sort();
  return Promise.all(files.map(async file => {
    const config = JSON.parse(await readFile(new URL(file, directory), 'utf8'));
    return { id: file.replace('.json', ''), label: config.name, config };
  }));
}

const seeds = { users: await profiles('users'), companies: await profiles('companies'), defaultEndpoint: 'https://pbapo.me' };

async function openApp(saved) {
  const dom = new JSDOM(html, { url: 'http://127.0.0.1:3000', runScripts: 'outside-only' });
  const { window } = dom;
  const sent = [];
  window.structuredClone = structuredClone;
  window.AbortSignal = AbortSignal;
  // jsdom does not implement native dialog rendering; these preserve open/close state for event tests.
  window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  window.HTMLDialogElement.prototype.close = function () { this.open = false; };
  window.fetch = async (url, options) => {
    if (url === '/api/profiles') return Response.json(seeds);
    assert.equal(url, '/api/requests');
    sent.push(JSON.parse(options.body));
    return Response.json({ accepted: true, status: 202, response: '{"status":"queued"}' });
  };
  if (saved) window.localStorage.setItem(storageKey, JSON.stringify(saved));
  window.eval(script);
  await new Promise(setImmediate);
  assert.equal(window.document.querySelector('#boot-error').hidden, true);
  const query = selector => window.document.querySelector(selector);
  const change = (selector, value) => {
    query(selector).value = value;
    query(selector).dispatchEvent(new window.Event('change', { bubbles: true }));
  };
  const submit = selector => query(selector).dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
  const stored = () => JSON.parse(window.localStorage.getItem(storageKey));
  return { dom, window, query, change, submit, stored, sent };
}

test('company and employee selectors exist only inside Account settings', async t => {
  const app = await openApp();
  t.after(() => app.window.close());
  const selects = [...app.window.document.querySelectorAll('select')];
  assert.equal(selects.length, 2);
  assert.ok(selects.every(select => select.closest('#account-dialog')));
  app.query('#request-order').click();
  assert.equal(app.query('#request-dialog').open, true);
  assert.equal(app.query('#request-person').textContent, 'Alex Morgan');
  assert.equal(app.query('#request-dialog select'), null);
});

test('switching companies filters employees, and cancelling preserves the saved account', async t => {
  const app = await openApp();
  t.after(() => app.window.close());
  app.query('.account-trigger').click();
  app.change('#account-company', 'meridian');
  assert.deepEqual([...app.query('#account-user').options].map(option => option.value), ['sam-rivera', 'taylor-brooks']);
  assert.equal(app.window.document.body.dataset.company, 'northstar');
  app.query('#account-dialog [data-close]').click();
  assert.equal(app.stored().active.companies, 'northstar');
  assert.equal(app.query('#header-name').textContent, 'Alex Morgan');
  app.query('.account-trigger').click();
  assert.equal(app.query('#account-company').value, 'northstar');
});

test('saving a Meridian account updates branding and survives reload with the correct outgoing configs', async t => {
  const app = await openApp();
  t.after(() => app.window.close());
  app.query('.account-trigger').click();
  app.change('#account-company', 'meridian');
  app.change('#account-user', 'taylor-brooks');
  app.submit('#account-form');
  assert.equal(app.query('#account-dialog').open, false);
  assert.equal(app.window.document.body.dataset.company, 'meridian');
  assert.equal(app.window.document.title, 'Meridian Labs · Overview');
  assert.equal(app.query('#brand-name').textContent, 'Meridian');
  assert.equal(app.query('#header-name').textContent, 'Taylor Brooks');
  assert.equal(app.query('#header-role').textContent, 'Operations specialist');

  const reloaded = await openApp(app.stored());
  t.after(() => reloaded.window.close());
  assert.equal(reloaded.window.document.body.dataset.company, 'meridian');
  reloaded.query('#request-order').click();
  reloaded.query('#request-text').value = 'Lab shelving for our operations team.';
  reloaded.submit('#request-form');
  await new Promise(setImmediate);
  assert.equal(reloaded.sent.length, 1);
  assert.deepEqual(reloaded.sent[0].payload.userConfig, seeds.users.find(user => user.id === 'taylor-brooks').config);
  assert.deepEqual(reloaded.sent[0].payload.companyConfig, seeds.companies.find(company => company.id === 'meridian').config);
  assert.equal(reloaded.query('#history-count').textContent, '1');

  reloaded.query('.account-trigger').click();
  reloaded.change('#account-company', 'northstar');
  reloaded.change('#account-user', 'jamie-chen');
  reloaded.submit('#account-form');
  assert.equal(reloaded.window.document.body.dataset.company, 'northstar');
  assert.equal(reloaded.query('#header-role').textContent, 'Intern');
  assert.equal(reloaded.query('#history-count').textContent, '0');
  assert.equal(reloaded.query('#empty-state').hidden, false);
  assert.equal(reloaded.stored().history.length, 1);
});

test('account settings reject an employee belonging to another company', async t => {
  const app = await openApp();
  t.after(() => app.window.close());
  app.query('.account-trigger').click();
  app.change('#account-company', 'meridian');
  app.query('#account-user').add(new app.window.Option('Alex Morgan', 'alex-morgan'));
  app.change('#account-user', 'alex-morgan');
  app.submit('#account-form');
  assert.equal(app.query('#account-feedback').hidden, false);
  assert.equal(app.stored().active.companies, 'northstar');
  assert.equal(app.query('#account-dialog').open, true);
});

test('the main workspace has role-specific activity and only one order entry point', async t => {
  const app = await openApp();
  t.after(() => app.window.close());
  const accounts = [
    ['northstar', 'alex-morgan', 'Company goals on track', 'Company initiatives'],
    ['northstar', 'jamie-chen', 'Onboarding modules', 'What you’re working on'],
    ['meridian', 'sam-rivera', 'Active studies', 'Study progress'],
    ['meridian', 'taylor-brooks', 'Rooms ready', 'Keeping things moving'],
  ];
  for (const [company, user, metric, projectsTitle] of accounts) {
    app.query('.account-trigger').click();
    app.change('#account-company', company);
    app.change('#account-user', user);
    app.submit('#account-form');
    assert.ok(app.query('#dashboard-stats').textContent.includes(metric));
    assert.equal(app.query('#projects-title').textContent, projectsTitle);
    assert.equal(app.window.document.querySelectorAll('.task-row').length, 4);
    assert.equal(app.window.document.querySelectorAll('.schedule-item').length, 3);
    assert.equal(app.window.document.querySelectorAll('.project-row').length, 3);
    assert.equal(app.window.document.querySelectorAll('.document-row').length, 3);
    const shell = app.window.document.body.cloneNode(true);
    shell.querySelectorAll('dialog, #toast').forEach(element => element.remove());
    assert.equal(shell.querySelectorAll('#request-order').length, 1);
    shell.querySelector('#request-order').remove();
    assert.doesNotMatch(shell.textContent, /\b(demo|sample|purchase|purchasing|procurement|order|supplier|configuration)\b/i);
    assert.equal(app.query('#purchasing-page'), null);
    assert.equal(app.query('#configurations-page'), null);
  }
  app.query('#request-order').click();
  assert.equal(app.query('#request-dialog').open, true);
  assert.equal(app.query('#request-person').textContent, 'Taylor Brooks');
});

test('completed dashboard tasks persist and remain separate for each account', async t => {
  const app = await openApp();
  t.after(() => app.window.close());
  app.query('.task-row input').click();
  assert.equal(app.query('#priority-count').textContent, '1 / 4 done');
  assert.equal(app.query('.task-row').classList.contains('completed'), true);
  const reloaded = await openApp(app.stored());
  t.after(() => reloaded.window.close());
  assert.equal(reloaded.query('.task-row input').checked, true);
  reloaded.query('.account-trigger').click();
  reloaded.change('#account-user', 'jamie-chen');
  reloaded.submit('#account-form');
  assert.equal(reloaded.query('#priority-count').textContent, '0 / 4 done');
  reloaded.query('.account-trigger').click();
  reloaded.change('#account-user', 'alex-morgan');
  reloaded.submit('#account-form');
  assert.equal(reloaded.query('#priority-count').textContent, '1 / 4 done');
});
