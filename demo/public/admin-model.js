export const statusLabels = {
  fulfilled: 'Fulfilled', denied: 'Denied', pending: 'Pending',
  verification_failed: 'Verification failed', verified: 'Awaiting purchase review',
};
export const proofLabels = { supported: 'Supported', contradicted: 'Contradicted', unverified: 'Incomplete', not_run: 'Not run' };
export const money = cents => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(cents / 100);
export const dateLabel = value => new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' }).format(new Date(value));

export function filterRequests(requests, filters = {}) {
  const query = (filters.query || '').trim().toLowerCase();
  return requests.filter(request => {
    const text = [request.id, request.title, request.requester, request.department, request.company,
      request.supplier, request.channel, request.description].join(' ').toLowerCase();
    return (!query || text.includes(query)) &&
      (!filters.company || request.company === filters.company) &&
      (!filters.status || request.status === filters.status) &&
      (!filters.proof || request.proof.status === filters.proof);
  }).sort((a, b) => filters.sort === 'amount' ? b.requestedCents - a.requestedCents || a.id.localeCompare(b.id)
    : b.createdAt.localeCompare(a.createdAt) || a.id.localeCompare(b.id));
}

export function summarizeRequests(requests) {
  return {
    total: requests.length,
    fulfilled: requests.filter(request => request.status === 'fulfilled').length,
    spend: requests.filter(request => request.status === 'fulfilled').reduce((total, request) => total + request.actualCents, 0),
    open: requests.filter(request => ['pending', 'verified'].includes(request.status)).length,
    exceptions: requests.filter(request => ['denied', 'verification_failed'].includes(request.status)).length,
  };
}

export function exportRecords(requests, snapshot) {
  return JSON.stringify({ demo: true, notice: 'Fictional demo records. Evidence and fulfillment are simulated; no formal proofs or real purchases.', snapshot, requests }, null, 2);
}
