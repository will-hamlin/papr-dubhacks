const $ = selector => document.querySelector(selector);
const storageKey = 'generic-enterprise-v1';
const profileRevision = 2;
let state;
let token = '';
let currentKind = 'users';
let editingId = null;
let pendingRequest = null;
let sending = false;
let toastTimer;

function notify(message) {
  $('#toast').textContent = message;
  $('#toast').hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 4000);
}

function persist() {
  try { localStorage.setItem(storageKey, JSON.stringify(state)); }
  catch { notify('Browser storage is full or unavailable. Changes will last only until reload.'); }
}

function feedback(selector, message, error = true) {
  const element = $(selector);
  element.textContent = message;
  element.classList.toggle('error', error);
  element.hidden = !message;
}

function initials(name) {
  return String(name || '?').split(/\s+/).slice(0, 2).map(part => part[0]).join('').toUpperCase();
}

function textElement(tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

function activeProfile(kind, id = state.active[kind]) {
  return state[kind].find(profile => profile.id === id);
}

function companyEmployees(companyId = state.active.companies) {
  const company = activeProfile('companies', companyId);
  return state.users.filter(profile => profile.config.companyId === company?.config.companyId);
}

function syncActiveEmployee() {
  const employees = companyEmployees();
  if (!employees.some(profile => profile.id === state.active.users)) {
    state.active.users = employees[0]?.id || '';
  }
}

function populateSelect(selector, kind, selected, companyId = state.active.companies) {
  const element = $(selector);
  const profiles = kind === 'users' ? companyEmployees(companyId) : state.companies;
  element.replaceChildren(...profiles.map(profile => new Option(
    kind === 'users' && profile.config.role ? `${profile.label} · ${profile.config.role}` : profile.label, profile.id)));
  const desiredId = selected || state.active[kind];
  element.value = profiles.some(profile => profile.id === desiredId) ? desiredId : profiles[0]?.id || '';
  element.disabled = profiles.length === 0;
  if (!profiles.length) element.add(new Option('No employee profiles for this company', ''));
}

function renderContext() {
  syncActiveEmployee();
  const user = activeProfile('users') || { label: 'Select an employee', config: {} };
  populateSelect('#active-user', 'users');
  populateSelect('#active-company', 'companies');
  populateSelect('#config-company', 'companies');
  $('#request-order').disabled = !state.active.users;
  $('#header-name').textContent = user.config.name || user.label;
  $('#header-avatar').textContent = initials(user.config.name || user.label);
  $('#header-role').textContent = user.config.role || 'Employee';
  $('#department').textContent = user.config.department || 'Not specified';
  $('#cost-center').textContent = user.config.costCenter ? `Cost center ${user.config.costCenter}` : 'No cost center specified';
  $('#config-count').textContent = state.users.length + state.companies.length;
  $('#service-status').textContent = state.endpoint ? 'Configured' : 'Not configured';
  $('#service-dot').classList.toggle('ready', Boolean(state.endpoint));
  $('#configure-service').replaceChildren(document.createTextNode(state.endpoint ? 'Connection settings ' : 'Configure connection '), textElement('span', '↗'));
  $('#request-destination').textContent = state.endpoint || 'No service configured';
}

function renderHistory() {
  $('#sent-count').replaceChildren(document.createTextNode(state.sentCount ?? state.history.length), textElement('span', 'requests'));
  $('#history-count').textContent = state.history.length;
  $('#empty-state').hidden = state.history.length > 0;
  const rows = state.history.map(record => {
    const row = document.createElement('tr');
    const request = document.createElement('td');
    const title = textElement('strong', record.payload.request.text);
    title.title = record.payload.request.text;
    request.append(title, textElement('small', `REQ-${record.payload.request.id.slice(0, 8).toUpperCase()}`));
    const person = document.createElement('td');
    person.append(document.createTextNode(record.userLabel), textElement('small', record.companyLabel));
    const date = textElement('td', new Date(record.payload.request.createdAt).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }));
    const status = document.createElement('td');
    status.append(textElement('span', 'Sent to service', 'delivery-pill'));
    const action = document.createElement('td');
    const view = textElement('button', 'View ↗', 'text-button');
    view.setAttribute('aria-label', `View request ${record.payload.request.id.slice(0, 8)}`);
    view.addEventListener('click', () => {
      $('#receipt-description').textContent = `Delivered to ${record.endpoint} · HTTP ${record.status}. Delivery does not mean the order has been approved.`;
      $('#receipt-payload').textContent = JSON.stringify(record.payload, null, 2);
      $('#receipt-response').textContent = record.response || '(Empty response)';
      $('#details-dialog').showModal();
    });
    action.append(view);
    row.append(request, person, date, status, action);
    return row;
  });
  $('#request-history').replaceChildren(...rows);
}

function showPage(page) {
  $('#overview-page').hidden = page !== 'overview';
  $('#configurations-page').hidden = page !== 'configurations';
  $('#breadcrumb-page').textContent = page === 'overview' ? 'Purchasing' : 'Configurations';
  document.querySelectorAll('[data-page]').forEach(button => {
    button.classList.toggle('active', button.dataset.page === page);
    if (button.dataset.page === page) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
  if (page === 'configurations') renderConfigs();
}

function renderConfigs() {
  $('#config-company-field').hidden = currentKind !== 'users';
  const profiles = currentKind === 'users' ? companyEmployees() : state.companies;
  const cards = profiles.map(profile => {
    const card = document.createElement('article');
    card.className = 'config-card';
    const description = currentKind === 'users'
      ? [profile.config.role, profile.config.department].filter(Boolean).join(' · ')
      : profile.config.industry;
    card.append(textElement('div', initials(profile.label), 'config-avatar'), textElement('h2', profile.label), textElement('p', description || 'Custom configuration'));
    const actions = textElement('div', '', 'config-actions');
    const edit = textElement('button', 'Edit JSON ↗', 'text-button');
    edit.addEventListener('click', () => openConfig(profile));
    const copy = textElement('button', 'Duplicate', 'text-button');
    copy.addEventListener('click', () => openConfig({ ...profile, id: null, label: `${profile.label} copy` }));
    const download = textElement('button', 'Download', 'text-button');
    download.addEventListener('click', () => {
      const url = URL.createObjectURL(new Blob([JSON.stringify(profile.config, null, 2) + '\n'], { type: 'application/json' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = `${profile.label.toLowerCase().replace(/[^a-z0-9]+/g, '-') || 'config'}.json`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    actions.append(edit, copy, download);
    card.append(actions);
    return card;
  });
  $('#config-list').replaceChildren(...cards);
}

function openConfig(profile) {
  editingId = profile?.id || null;
  $('#config-type-label').textContent = currentKind === 'users' ? 'EMPLOYEE PROFILE' : 'COMPANY PROFILE';
  $('#config-dialog-title').textContent = editingId ? 'Edit configuration' : 'New configuration';
  $('#config-label').value = profile?.label || '';
  const blankConfig = currentKind === 'users'
    ? { name: '', companyId: activeProfile('companies').config.companyId }
    : { name: '', companyId: '' };
  $('#config-json').value = JSON.stringify(profile?.config || blankConfig, null, 2);
  feedback('#config-feedback', '');
  $('#config-dialog').showModal();
}

function buildPayload() {
  return {
    request: { ...pendingRequest, text: $('#request-text').value.trim() },
    userConfig: structuredClone(activeProfile('users', $('#request-user').value)?.config || {}),
    companyConfig: structuredClone(activeProfile('companies', $('#request-company').value).config),
  };
}

function updatePreview() {
  $('#payload-preview').textContent = JSON.stringify(buildPayload(), null, 2);
  $('#send-request').disabled = !$('#request-user').value;
}

function openRequest() {
  if (!state) return;
  pendingRequest = { id: crypto.randomUUID(), createdAt: new Date().toISOString() };
  $('#request-text').value = '';
  populateSelect('#request-user', 'users');
  populateSelect('#request-company', 'companies');
  feedback('#request-feedback', '');
  updatePreview();
  $('#request-dialog').showModal();
  $('#request-text').focus();
}

function openConnection() {
  $('#service-url').value = state.endpoint;
  $('#service-token').value = token;
  feedback('#service-feedback', '');
  $('#service-dialog').showModal();
}

document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
document.querySelectorAll('[data-page]').forEach(button => button.addEventListener('click', () => { if (state) showPage(button.dataset.page); }));
document.querySelectorAll('[data-kind]').forEach(button => button.addEventListener('click', () => {
  currentKind = button.dataset.kind;
  document.querySelectorAll('[data-kind]').forEach(tab => {
    tab.classList.toggle('selected', tab === button);
    tab.setAttribute('aria-pressed', String(tab === button));
  });
  renderConfigs();
}));
$('#manage-configs').addEventListener('click', () => { if (state) showPage('configurations'); });
$('#new-config').addEventListener('click', () => openConfig());
for (const kind of ['users', 'companies']) {
  $(`#active-${kind === 'users' ? 'user' : 'company'}`).addEventListener('change', event => {
    state.active[kind] = event.target.value;
    syncActiveEmployee();
    persist();
    renderContext();
  });
}
$('#config-company').addEventListener('change', event => {
  state.active.companies = event.target.value;
  syncActiveEmployee();
  persist();
  renderContext();
  renderConfigs();
});
$('#request-order').addEventListener('click', openRequest);
$('#empty-request').addEventListener('click', openRequest);
$('#configure-service').addEventListener('click', () => { if (state) openConnection(); });
$('#request-settings').addEventListener('click', openConnection);
$('#request-text').addEventListener('input', updatePreview);
$('#request-user').addEventListener('change', updatePreview);
$('#request-company').addEventListener('change', () => {
  populateSelect('#request-user', 'users', $('#request-user').value, $('#request-company').value);
  updatePreview();
});

$('#service-form').addEventListener('submit', event => {
  event.preventDefault();
  try {
    const url = new URL($('#service-url').value.trim());
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw new Error('Use an HTTP or HTTPS URL without embedded credentials.');
    state.endpoint = url.href;
    token = $('#service-token').value.trim();
    persist();
    renderContext();
    $('#service-dialog').close();
    notify('Connection saved. Ready to send a request.');
  } catch (error) { feedback('#service-feedback', error.message); }
});

$('#config-form').addEventListener('submit', event => {
  event.preventDefault();
  try {
    const config = JSON.parse($('#config-json').value);
    if (!config || typeof config !== 'object' || Array.isArray(config)) throw new Error('Configuration must be a JSON object, not an array or single value.');
    const label = $('#config-label').value.trim();
    if (!label) throw new Error('Give this profile a label.');
    if (typeof config.companyId !== 'string' || !config.companyId.trim()) throw new Error('Include a companyId for this profile.');
    if (currentKind === 'users' && !state.companies.some(company => company.config.companyId === config.companyId)) {
      throw new Error('The employee companyId must match a saved company.');
    }
    if (currentKind === 'companies') {
      if (state.companies.some(company => company.id !== editingId && company.config.companyId === config.companyId)) {
        throw new Error('Each company needs a unique companyId.');
      }
      const previousCompanyId = activeProfile('companies', editingId)?.config.companyId;
      if (previousCompanyId && previousCompanyId !== config.companyId) {
        state.users.forEach(user => { if (user.config.companyId === previousCompanyId) user.config.companyId = config.companyId; });
      }
    }
    const profile = { id: editingId || crypto.randomUUID(), label, config };
    if (editingId) state[currentKind] = state[currentKind].map(item => item.id === editingId ? profile : item);
    else state[currentKind].push(profile);
    renderContext();
    persist();
    renderConfigs();
    $('#config-dialog').close();
    notify('Configuration saved.');
  } catch (error) { feedback('#config-feedback', `Could not save: ${error.message}`); }
});

$('#request-dialog').addEventListener('cancel', event => { if (sending) event.preventDefault(); });
$('#request-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (sending) return;
  if (!$('#request-user').value) return feedback('#request-feedback', 'Choose an employee for this company before sending.');
  if (!$('#request-text').value.trim()) return feedback('#request-feedback', 'Describe what you would like to order.');
  if (!state.endpoint) {
    feedback('#request-feedback', 'Add your order service URL before sending.');
    openConnection();
    return;
  }
  const payload = buildPayload();
  const endpoint = state.endpoint;
  const userLabel = activeProfile('users', $('#request-user').value).label;
  const companyLabel = activeProfile('companies', $('#request-company').value).label;
  sending = true;
  $('#request-form').querySelectorAll('button, input, textarea, select').forEach(element => { element.disabled = true; });
  $('#send-request').textContent = 'Sending…';
  feedback('#request-feedback', 'Sending your request and both profiles…', false);
  try {
    const response = await fetch('/api/requests', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ endpoint, token, payload }), signal: AbortSignal.timeout(25000),
    });
    const result = await response.json();
    if (!response.ok || !result.accepted) {
      throw new Error([result.error || 'The service did not accept this request.', result.response].filter(Boolean).join('\n\n'));
    }
    state.sentCount = (state.sentCount ?? state.history.length) + 1;
    state.history.unshift({ payload, endpoint, userLabel, companyLabel, status: result.status, response: result.response });
    state.history = state.history.slice(0, 25);
    persist();
    renderHistory();
    $('#request-dialog').close();
    notify('Request sent to the order service.');
  } catch (error) {
    feedback('#request-feedback', error.name === 'TimeoutError' || error instanceof TypeError
      ? 'Delivery could not be confirmed. The service may have received this request; check before retrying.'
      : error.message);
  } finally {
    sending = false;
    $('#request-form').querySelectorAll('button, input, textarea, select').forEach(element => { element.disabled = false; });
    $('#send-request').replaceChildren(document.createTextNode('Send request '), textElement('span', '↗'));
  }
});

async function initialize() {
  try {
    const response = await fetch('/api/profiles');
    if (!response.ok) throw new Error('Unable to load demo profiles.');
    const seeds = await response.json();
    let saved;
    try { saved = JSON.parse(localStorage.getItem(storageKey)); } catch { /* Storage may be disabled. */ }
    const validProfiles = profiles => Array.isArray(profiles) && profiles.length > 0 && profiles.every(item =>
      item && typeof item.id === 'string' && typeof item.label === 'string' && item.config && typeof item.config === 'object' && !Array.isArray(item.config));
    state = {
      profileRevision,
      users: saved?.profileRevision === profileRevision && validProfiles(saved?.users) ? saved.users : seeds.users,
      companies: saved?.profileRevision === profileRevision && validProfiles(saved?.companies) ? saved.companies : seeds.companies,
      endpoint: typeof saved?.endpoint === 'string' ? saved.endpoint : seeds.defaultEndpoint,
      history: Array.isArray(saved?.history) ? saved.history.filter(item => item?.payload?.request?.id && typeof item.payload.request.text === 'string').slice(0, 25) : [],
      sentCount: Number.isSafeInteger(saved?.sentCount) && saved.sentCount >= 0 ? saved.sentCount : undefined,
    };
    state.active = {};
    for (const kind of ['users', 'companies']) {
      const defaultId = kind === 'companies' && state.companies.some(item => item.id === 'northstar') ? 'northstar' : state[kind][0].id;
      state.active[kind] = state[kind].some(item => item.id === saved?.active?.[kind]) ? saved.active[kind] : defaultId;
    }
    renderContext();
    persist();
    renderHistory();
    showPage('overview');
  } catch (error) {
    feedback('#boot-error', `${error.message} Start the app with npm start and reload this page.`);
  }
}
initialize();
