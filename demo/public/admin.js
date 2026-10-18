import { statusLabels, proofLabels, money, dateLabel, filterRequests, summarizeRequests, exportRecords } from './admin-model.js';

const $ = selector => document.querySelector(selector);
const escape = value => String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const pill = (status, label) => `<span class="pill ${escape(status)}">${escape(label)}</span>`;
let data;
let filtered = [];
let returnFocus;

function render() {
  filtered = filterRequests(data.requests, { query: $('#search').value, company: $('#company').value, status: $('#status').value, proof: $('#proof').value, sort: $('#sort').value });
  const summary = summarizeRequests(filtered);
  $('#metrics').innerHTML = [
    ['Fulfilled spend', money(summary.spend), `${summary.fulfilled} fulfilled · simulated purchases only`],
    ['Requests in view', summary.total, 'Across the current filters'],
    ['Open requests', summary.open, 'Pending or awaiting purchase review'],
    ['Exceptions', summary.exceptions, 'Denied or verification failed'],
  ].map(([label, value, note]) => `<article class="metric"><p class="metric-label">${escape(label)}</p><p class="metric-value">${escape(value)}</p><p class="metric-note">${escape(note)}</p></article>`).join('');
  $('#rows').innerHTML = filtered.map(request => `<tr>
    <td><button class="request-link" data-request="${escape(request.id)}">${escape(request.title)}</button><span class="subline"><span class="request-ref">${escape(request.id)}</span>${escape(request.requester)} · ${escape(request.department)}</span></td>
    <td>${escape(request.company)}<span class="subline">${escape(request.supplier || 'No supplier selected')}</span></td>
    <td class="amount">${money(request.requestedCents)}<span class="subline">${request.quantity} ${request.quantity === 1 ? 'unit' : 'units'}</span></td>
    <td>${pill(request.status, statusLabels[request.status])}</td>
    <td><span class="proof-state ${escape(request.proof.status)}">${escape(proofLabels[request.proof.status])}</span></td>
    <td>${dateLabel(request.createdAt)}<span class="subline">${escape(request.channel)}</span></td>
    <td><button class="row-arrow" data-request="${escape(request.id)}" aria-label="Review ${escape(request.id)}">↗</button></td>
  </tr>`).join('');
  $('#empty').hidden = filtered.length !== 0;
  $('#record-count').textContent = summary.total;
  $('#footer-count').textContent = `${summary.total} of ${data.requests.length} fictional requests · all matching rows shown`;
  $('#result-announcement').textContent = `${summary.total} requests match the filters.`;
}

function detail(request, trigger) {
  returnFocus = trigger;
  $('#detail-id').textContent = request.id;
  const facts = [
    ['Requested by', `${request.requester} · ${request.department}`], ['Company', request.company],
    ['Requested amount', `${money(request.requestedCents)} · ${request.quantity} ${request.quantity === 1 ? 'unit' : 'units'}`],
    ['Fulfilled spend', request.status === 'fulfilled' ? money(request.actualCents) : 'No purchase recorded'],
    ['Supplier', request.supplier || 'Not selected'], ['Request channel', request.channel],
    ['Policy snapshot', request.policy.version], ['Per-request limit', money(request.policy.ceilingCents)],
  ];
  $('#detail-content').innerHTML = `<h2 id="detail-title" class="detail-title">${escape(request.title)}</h2>
    <div class="detail-status">${pill(request.status, statusLabels[request.status])}${pill(request.proof.status, `${proofLabels[request.proof.status]} evidence`)}</div>
    <p class="description">${escape(request.description)}</p>
    <section class="detail-section"><h3>Request context</h3><dl class="facts">${facts.map(([key, value]) => `<div><dt>${escape(key)}</dt><dd>${escape(value)}</dd></div>`).join('')}</dl></section>
    <section class="detail-section"><h3>Decision record</h3><p class="decision-note">${escape(request.decision)}</p></section>
    <section class="detail-section"><h3>Proof &amp; evidence review</h3><p class="source-note">Simulated listing checks for this fixture. These records are not cryptographic certificates or formal solver proofs. Optimality is not evaluated.</p>
      ${request.proof.checks.length ? `<div class="evidence">${request.proof.checks.map(check => `<div class="evidence-item"><strong>${escape(check.condition)}</strong>${pill(check.status, proofLabels[check.status])}<p>Requirement: ${escape(check.required)}<br>Observed in fixture: ${escape(check.observed)}</p></div>`).join('')}</div>` : `<div class="evidence-empty">${escape(request.proof.note)}</div>`}
      ${request.proof.source ? `<p class="source-note" style="margin-top:14px">Fixture source (reserved .example domain, not fetched):<br><span class="source-url">${escape(request.proof.source)}</span><br>Evidence snapshot: ${escape(request.proof.capturedAt)}<br>Record: ${escape(request.proof.id)} · ${escape(request.proof.note)}</p>` : ''}
    </section>
    <section class="detail-section"><h3>Activity trail</h3><ol class="timeline">${request.events.map(event => `<li><strong>${escape(event.label)}</strong><time datetime="${escape(event.at)}">${escape(event.at.replace('T', ' ').replace('Z', ' UTC'))}</time><p>${escape(event.detail)}</p></li>`).join('')}</ol></section>`;
  $('#detail').showModal();
}

function closeDetail() { $('#detail').close(); }
$('#close-detail').addEventListener('click', closeDetail);
$('#detail').addEventListener('close', () => returnFocus?.focus());
$('#detail').addEventListener('click', event => { if (event.target === $('#detail')) closeDetail(); });
$('#rows').addEventListener('click', event => {
  const trigger = event.target.closest('[data-request]');
  if (trigger) detail(data.requests.find(request => request.id === trigger.dataset.request), trigger);
});
$('#search').addEventListener('input', () => { if (data) render(); });
for (const id of ['company', 'status', 'proof', 'sort']) $(`#${id}`).addEventListener('change', () => { if (data) render(); });
$('#reset').addEventListener('click', () => {
  for (const id of ['search', 'company', 'status', 'proof']) $(`#${id}`).value = '';
  $('#sort').value = 'newest';
  if (data) render();
});
$('#export').addEventListener('click', () => {
  const url = URL.createObjectURL(new Blob([exportRecords(filtered, data.snapshot)], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url; link.download = 'papr-fictional-finance-records.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

async function boot() {
  try {
    const response = await fetch('/api/admin/demo-requests');
    if (!response.ok) throw new Error('Ledger unavailable');
    data = await response.json();
    if (data.demo !== true || !Array.isArray(data.requests)) throw new Error('Expected demo ledger');
    for (const company of [...new Set(data.requests.map(request => request.company))].sort()) {
      const option = document.createElement('option'); option.value = company; option.textContent = company; $('#company').append(option);
    }
    $('#snapshot').textContent = `${dateLabel(data.periodStart)} – ${dateLabel(data.snapshot)}, 2026 · fictional history`;
    render(); $('#export').disabled = false;
  } catch {
    data = undefined;
    $('#load-error').textContent = 'The demo ledger could not be loaded. Reload this page after the demo server is running.';
    $('#load-error').hidden = false; $('#snapshot').textContent = 'Demo ledger unavailable';
    $('#footer-count').textContent = 'No records loaded';
  }
}
boot();
