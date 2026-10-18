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

const dashboardContent = {
  ceo: {
    subtitle: 'A clear view of your teams, priorities, and the week ahead.',
    focus: 'Bring the Q4 strategy into focus',
    stats: [
      { label: 'Company goals on track', value: '8 / 10', note: 'Two need a closer look', bars: [36, 44, 40, 55, 62, 72, 80] },
      { label: 'Team engagement', value: '88%', note: '+6 points from last pulse', bars: [46, 52, 63, 56, 74, 82, 88] },
      { label: 'Open roles', value: '4', note: 'Two final interviews this week', bars: [78, 64, 64, 52, 45, 45, 35] },
    ],
    prioritiesTitle: 'On your desk', projectsTitle: 'Company initiatives',
    tasks: [
      { id: 'ceo-board', title: 'Review the board presentation', detail: 'Strategy team · updated this morning', tag: 'Today' },
      { id: 'ceo-hiring', title: 'Leave feedback on the leadership shortlist', detail: 'People team · two candidates ready', tag: 'Today' },
      { id: 'ceo-allhands', title: 'Record a short all-hands introduction', detail: 'Communications · 3-minute recording', tag: 'This week' },
      { id: 'ceo-roadmap', title: 'Comment on the customer experience roadmap', detail: 'Client services · draft 03', tag: 'Review' },
    ],
    projects: [
      { name: 'Q4 operating plan', owner: 'Morgan Lee · Strategy', progress: 76, status: 'On track' },
      { name: 'Client onboarding refresh', owner: 'Priya Shah · Client services', progress: 58, status: 'In progress' },
      { name: 'Leadership development cohort', owner: 'Jordan Ellis · People', progress: 34, status: 'Planning' },
    ],
    schedule: [
      { time: '09:00', title: 'Leadership stand-up', detail: '30 min · Boardroom', people: ['ML', 'PS', 'JE'] },
      { time: '11:30', title: 'Customer advisory conversation', detail: '45 min · Video call', people: ['PS', 'RK'] },
      { time: '15:00', title: 'Q4 strategy working session', detail: '60 min · Strategy room', people: ['ML', 'JE'] },
    ],
    scheduleFooter: 'Focus time reserved from 1:00–2:30 PM',
    documents: [{ title: 'Q4 board briefing', meta: 'Presentation · updated today', kind: 'SLD' }, { title: 'October team pulse', meta: 'Report · People team', kind: 'PDF' }, { title: 'Leadership meeting notes', meta: 'Document · shared yesterday', kind: 'DOC' }],
    updates: [
      { initials: 'PS', author: 'Priya Shah', team: 'Client services', text: 'The new client welcome guide is ready for team review. Thanks to everyone who shared feedback from the pilot.', time: '45 minutes ago' },
      { initials: 'JE', author: 'Jordan Ellis', team: 'People & culture', text: 'Our next all-hands includes a five-minute spotlight on the Seattle team. Add your questions before Wednesday.', time: '2 hours ago' },
    ],
    note: { label: 'PEOPLE FIRST', title: 'A small thank-you goes a long way.', body: 'This week’s team spotlight: Client Services, for making the onboarding pilot feel effortless.' },
  },
  intern: {
    subtitle: 'Your next steps, helpful people, and a little room to learn.',
    focus: 'Finish your first project and share what you learned',
    stats: [
      { label: 'Onboarding modules', value: '6 / 8', note: 'You’re nearly through the essentials', bars: [15, 28, 34, 48, 56, 65, 75] },
      { label: 'Learning hours', value: '12.5', note: 'This month · 16-hour goal', bars: [25, 34, 42, 53, 60, 67, 78] },
      { label: 'Project milestones', value: '3 / 5', note: 'Your first team presentation is next', bars: [18, 20, 35, 40, 55, 58, 60] },
    ],
    prioritiesTitle: 'Your next steps', projectsTitle: 'What you’re working on',
    tasks: [
      { id: 'intern-security', title: 'Finish the information security module', detail: 'Learning hub · about 20 minutes', tag: 'Today' },
      { id: 'intern-notes', title: 'Share notes from the customer team shadow', detail: 'Mentor: Morgan Lee · shared notebook', tag: 'Today' },
      { id: 'intern-draft', title: 'Prepare three slides for Friday’s showcase', detail: 'Intern project · first draft', tag: 'This week' },
      { id: 'intern-coffee', title: 'Write down questions for your mentor', detail: 'Weekly check-in · bring one challenge', tag: 'This week' },
    ],
    projects: [
      { name: 'New-starter welcome guide', owner: 'You + Morgan Lee', progress: 65, status: 'Drafting' },
      { name: 'Customer feedback themes', owner: 'Client services rotation', progress: 40, status: 'Research' },
      { name: 'First-month learning plan', owner: 'People & culture', progress: 75, status: 'On track' },
    ],
    schedule: [
      { time: '09:30', title: 'Operations team check-in', detail: '15 min · Team area', people: ['ML', 'AC'] },
      { time: '12:00', title: 'New-starter lunch', detail: '45 min · Kitchen, floor 2', people: ['RP', 'KT'] },
      { time: '14:30', title: 'Mentor catch-up', detail: '30 min · Morgan Lee', people: ['ML'] },
    ],
    scheduleFooter: 'Learning block reserved from 3:00–4:00 PM',
    documents: [{ title: 'Your first 30 days', meta: 'Checklist · People team', kind: 'DOC' }, { title: 'Who to ask for what', meta: 'Team directory · updated Monday', kind: 'PDF' }, { title: 'Showcase slide template', meta: 'Presentation · Intern cohort', kind: 'SLD' }],
    updates: [
      { initials: 'ML', author: 'Morgan Lee', team: 'Your mentor', text: 'Nice work on the interview notes. For our next catch-up, pick one pattern you noticed and one question you want to explore.', time: '30 minutes ago' },
      { initials: 'JE', author: 'Jordan Ellis', team: 'People & culture', text: 'The new-starter lunch is in the second-floor kitchen today. Bring your questions; the team is looking forward to meeting you.', time: '1 hour ago' },
    ],
    note: { label: 'MEET YOUR PEOPLE', title: 'You don’t have to figure it out alone.', body: 'Morgan is your mentor. Priya can help with client questions, and Jordan is your go-to for all things workplace.' },
  },
  researcher: {
    subtitle: 'Your studies, shared knowledge, and the next useful question.',
    focus: 'Turn this week’s observations into a clear story',
    stats: [
      { label: 'Active studies', value: '3', note: 'Two in analysis · one in planning', bars: [28, 28, 44, 44, 65, 65, 65] },
      { label: 'Datasets reviewed', value: '18 / 24', note: 'Six remaining in the current batch', bars: [15, 23, 40, 48, 56, 65, 75] },
      { label: 'Research notes', value: '12', note: 'Four added this week', bars: [20, 32, 35, 51, 62, 75, 88] },
    ],
    prioritiesTitle: 'At the research bench', projectsTitle: 'Study progress',
    tasks: [
      { id: 'researcher-analysis', title: 'Review the latest materials dataset', detail: 'Project Atlas · analysis batch 04', tag: 'Today' },
      { id: 'researcher-notes', title: 'Add observations to the shared notebook', detail: 'Surface stability study · team notes', tag: 'Today' },
      { id: 'researcher-review', title: 'Comment on Lena’s methods summary', detail: 'Peer review · draft 02', tag: 'Review' },
      { id: 'researcher-seminar', title: 'Prepare a figure for the research seminar', detail: 'Friday discussion · one key finding', tag: 'This week' },
    ],
    projects: [
      { name: 'Atlas · materials stability', owner: 'Sam Rivera + Lena Ortiz', progress: 72, status: 'Analysis' },
      { name: 'Surface imaging comparison', owner: 'Imaging group', progress: 46, status: 'In review' },
      { name: 'Open research notebook', owner: 'Cross-lab collaboration', progress: 85, status: 'On track' },
    ],
    schedule: [
      { time: '09:15', title: 'Research group stand-up', detail: '20 min · Collaboration room', people: ['LO', 'AN'] },
      { time: '11:00', title: 'Atlas analysis review', detail: '45 min · Room B-12', people: ['LO', 'EH'] },
      { time: '14:00', title: 'Visiting researcher seminar', detail: '60 min · Lecture room', people: ['AN', 'JW'] },
    ],
    scheduleFooter: 'Analysis time reserved from 3:00–5:00 PM',
    documents: [{ title: 'Atlas study notebook', meta: 'Notebook · last edited today', kind: 'DOC' }, { title: 'Materials analysis overview', meta: 'Report · draft for discussion', kind: 'PDF' }, { title: 'Research seminar reading list', meta: 'Reading list · 6 papers', kind: 'DOC' }],
    updates: [
      { initials: 'LO', author: 'Lena Ortiz', team: 'Materials group', text: 'The latest Atlas figures are in the shared notebook. I’ve highlighted two trends for discussion in our analysis review.', time: '25 minutes ago' },
      { initials: 'AN', author: 'Arun Nair', team: 'Research community', text: 'This afternoon’s seminar covers reproducible data visualization. The reading list is ready for anyone who wants a head start.', time: '1 hour ago' },
    ],
    note: { label: 'CURIOSITY, SHARED', title: 'Bring the question that isn’t solved yet.', body: 'Friday’s open notebook session is a space for unfinished ideas. One figure, one question, and a few fresh perspectives.' },
  },
  operations: {
    subtitle: 'The people, spaces, and moving parts that keep the lab running.',
    focus: 'Keep every team ready for a smooth week',
    stats: [
      { label: 'Rooms ready', value: '11 / 12', note: 'One room scheduled for inspection', bars: [62, 71, 76, 85, 80, 90, 92] },
      { label: 'Service tickets closed', value: '17', note: 'This week · 3 still open', bars: [20, 32, 43, 52, 68, 76, 90] },
      { label: 'Team coverage', value: '96%', note: 'Next week’s roster is almost set', bars: [66, 76, 82, 79, 88, 91, 96] },
    ],
    prioritiesTitle: 'Operations checklist', projectsTitle: 'Keeping things moving',
    tasks: [
      { id: 'operations-room', title: 'Confirm Room B-12 is ready for the review', detail: 'Research team · before 11:00 AM', tag: 'Today' },
      { id: 'operations-roster', title: 'Fill the final gap in next week’s rota', detail: 'Facilities coverage · Thursday afternoon', tag: 'Today' },
      { id: 'operations-visitor', title: 'Send the visitor arrival brief to reception', detail: 'Guest seminar · arrival at 1:30 PM', tag: 'Today' },
      { id: 'operations-handover', title: 'Update the weekly facilities handover', detail: 'Shared log · include open tickets', tag: 'This week' },
    ],
    projects: [
      { name: 'Lab readiness walkthroughs', owner: 'Facilities team', progress: 92, status: 'On track' },
      { name: 'Visitor experience refresh', owner: 'Taylor Brooks + Eva Hart', progress: 55, status: 'In progress' },
      { name: 'Shared-space scheduling', owner: 'Research operations', progress: 68, status: 'Review' },
    ],
    schedule: [
      { time: '08:45', title: 'Facilities morning briefing', detail: '15 min · Operations desk', people: ['EH', 'MT'] },
      { time: '10:30', title: 'Shared-space walkthrough', detail: '30 min · Building B', people: ['MT'] },
      { time: '13:30', title: 'Visiting speaker arrival', detail: '20 min · Main reception', people: ['EH', 'AN'] },
    ],
    scheduleFooter: 'Afternoon coverage: Morgan and Eva',
    documents: [{ title: 'Weekly team rota', meta: 'Schedule · next week', kind: 'XLS' }, { title: 'Building B handover log', meta: 'Document · updated today', kind: 'DOC' }, { title: 'Visitor arrival brief', meta: 'Guide · Reception team', kind: 'PDF' }],
    updates: [
      { initials: 'EH', author: 'Eva Hart', team: 'Workplace experience', text: 'The visitor sign-in guide is now in the reception folder. We’ve added a short route map to the lecture room.', time: '40 minutes ago' },
      { initials: 'MT', author: 'Morgan Tan', team: 'Facilities', text: 'The second-floor quiet room will be unavailable Thursday morning for a routine inspection. The east meeting room is available instead.', time: '2 hours ago' },
    ],
    note: { label: 'BEHIND EVERY GOOD DAY', title: 'The small details make the difference.', body: 'Thanks to the operations team for keeping this week’s visiting-researcher programme running smoothly.' },
  },
};

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

function renderDashboard() {
  const user = activeProfile('users');
  const company = activeProfile('companies');
  const role = String(user?.config.role || '').toLowerCase();
  const roleKey = role.includes('ceo') ? 'ceo' : role.includes('intern') ? 'intern'
    : role.includes('research') ? 'researcher' : 'operations';
  const content = dashboardContent[roleKey];
  const name = String(user?.config.name || user?.label || 'there').split(' ')[0];
  const companyName = company.config.name || company.label;
  const now = new Date();
  $('#dashboard-date').textContent = now.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' });
  $('#calendar-day').textContent = now.getDate();
  $('#dashboard-kicker').textContent = `${companyName.toUpperCase()} / ${String(user?.config.department || 'YOUR WORKSPACE').toUpperCase()}`;
  $('#dashboard-greeting').textContent = `Welcome back, ${name}.`;
  $('#dashboard-subtitle').textContent = content.subtitle;
  $('#dashboard-focus').textContent = content.focus;
  $('#request-order').disabled = !user;
  $('#dashboard-footer-company').textContent = companyName;

  $('#dashboard-stats').replaceChildren(...content.stats.map(stat => {
    const card = textElement('article', '', 'dashboard-stat');
    const copy = textElement('div', '', 'stat-copy');
    copy.append(textElement('span', stat.label, 'stat-label'), textElement('strong', stat.value, 'stat-number'), textElement('span', stat.note, 'stat-note'));
    const sparkline = textElement('div', '', 'stat-sparkline');
    sparkline.setAttribute('aria-hidden', 'true');
    stat.bars.forEach(height => {
      const bar = document.createElement('span');
      bar.style.height = `${height}%`;
      sparkline.append(bar);
    });
    card.append(copy, sparkline);
    return card;
  }));

  $('#priorities-title').textContent = content.prioritiesTitle;
  const taskKey = task => `${company.id}:${user?.id || 'none'}:${task.id}`;
  const updateTaskCount = () => {
    const done = content.tasks.filter(task => state.completedTasks[taskKey(task)] === true).length;
    $('#priority-count').textContent = `${done} / ${content.tasks.length} done`;
  };
  $('#dashboard-tasks').replaceChildren(...content.tasks.map(task => {
    const row = textElement('label', '', 'task-row');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = state.completedTasks[taskKey(task)] === true;
    row.classList.toggle('completed', checkbox.checked);
    const copy = textElement('span', '', 'task-copy');
    copy.append(textElement('strong', task.title), textElement('span', task.detail));
    checkbox.addEventListener('change', () => {
      state.completedTasks[taskKey(task)] = checkbox.checked;
      row.classList.toggle('completed', checkbox.checked);
      updateTaskCount();
      persist();
    });
    row.append(checkbox, copy, textElement('span', task.tag, `task-tag ${task.tag === 'Today' ? 'today' : ''}`));
    return row;
  }));
  updateTaskCount();

  $('#projects-title').textContent = content.projectsTitle;
  $('#dashboard-projects').replaceChildren(...content.projects.map(project => {
    const row = textElement('article', '', 'project-row');
    const heading = textElement('div', '', 'project-heading');
    heading.append(textElement('strong', project.name), textElement('span', project.status, 'project-status'));
    const progress = textElement('div', '', 'project-progress');
    const track = textElement('div', '', 'progress-track');
    track.setAttribute('role', 'progressbar');
    track.setAttribute('aria-label', project.name);
    track.setAttribute('aria-valuemin', '0');
    track.setAttribute('aria-valuemax', '100');
    track.setAttribute('aria-valuenow', String(project.progress));
    const fill = document.createElement('span');
    fill.style.width = `${project.progress}%`;
    track.append(fill);
    progress.append(track, textElement('span', `${project.progress}%`));
    row.append(heading, textElement('p', project.owner), progress);
    return row;
  }));

  $('#dashboard-schedule').replaceChildren(...content.schedule.map(meeting => {
    const row = textElement('article', '', 'schedule-item');
    const copy = textElement('div', '', 'schedule-copy');
    copy.append(textElement('strong', meeting.title), textElement('span', meeting.detail));
    const people = textElement('div', '', 'meeting-people');
    people.setAttribute('aria-hidden', 'true');
    people.append(...meeting.people.map(person => textElement('span', person)));
    copy.append(people);
    row.append(textElement('time', meeting.time), copy);
    return row;
  }));
  $('#schedule-footer').textContent = content.scheduleFooter;

  $('#dashboard-documents').replaceChildren(...content.documents.map(document => {
    const row = textElement('article', '', 'document-row');
    const copy = textElement('div', '', 'document-copy');
    copy.append(textElement('strong', document.title), textElement('span', document.meta));
    row.append(textElement('span', document.kind, 'document-type'), copy);
    return row;
  }));

  $('#dashboard-updates').replaceChildren(...content.updates.map(update => {
    const row = textElement('article', '', 'update-row');
    const copy = textElement('div', '', 'update-copy');
    const heading = textElement('div', '', 'update-heading');
    heading.append(textElement('strong', update.author), textElement('span', update.team));
    copy.append(heading, textElement('p', update.text), textElement('span', update.time, 'update-time'));
    row.append(textElement('span', update.initials, 'avatar'), copy);
    return row;
  }));
  $('#team-note-label').textContent = content.note.label;
  $('#team-note-title').textContent = content.note.title;
  $('#team-note-body').textContent = content.note.body;
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
  const company = activeProfile('companies');
  const companyName = company.config.name || company.label;
  const isMeridian = company.id === 'meridian' || company.config.companyId === 'CO-003';
  document.body.dataset.company = isMeridian ? 'meridian' : 'northstar';
  document.title = `${companyName} · Overview`;
  $('meta[name="theme-color"]').content = isMeridian ? '#a43e42' : '#182d43';
  $('#brand-name').textContent = companyName.replace(/\s+(Industries|Labs)$/, '');
  $('#brand-subtitle').textContent = isMeridian ? 'LABS / INTERNAL' : 'INDUSTRIES';
  $('#brand-link').setAttribute('aria-label', `${companyName} home`);
  $('#sidebar-company').textContent = companyName;
  $('#sidebar-caption').textContent = isMeridian ? 'Room for the next discovery.' : 'Built for the everyday.';
  $('#workspace-title').textContent = isMeridian ? 'Research workspace' : 'Employee workspace';
  $('#config-company-name').textContent = companyName;
  $('#header-name').textContent = user.config.name || user.label;
  $('#header-avatar').textContent = initials(user.config.name || user.label);
  $('#header-role').textContent = user.config.role || 'Employee';
  $('#request-destination').textContent = state.endpoint || 'No service configured';
  renderDashboard();
}

function renderHistory() {
  const companyId = activeProfile('companies').config.companyId;
  const history = state.history.filter(record => record.payload.companyConfig?.companyId === companyId);
  $('#history-count').textContent = history.length;
  $('#empty-state').hidden = history.length > 0;
  const rows = history.map(record => {
    const row = document.createElement('tr');
    const request = document.createElement('td');
    const title = textElement('strong', record.payload.request.text);
    title.title = record.payload.request.text;
    request.append(title, textElement('small', `REQ-${record.payload.request.id.slice(0, 8).toUpperCase()}`));
    const person = document.createElement('td');
    person.append(document.createTextNode(record.userLabel), textElement('small', record.companyLabel));
    const date = textElement('td', new Date(record.payload.request.createdAt).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }));
    const status = document.createElement('td');
    status.append(textElement('span', 'Submitted', 'delivery-pill'));
    const action = document.createElement('td');
    const view = textElement('button', 'View ↗', 'text-button');
    view.setAttribute('aria-label', `View request ${record.payload.request.id.slice(0, 8)}`);
    view.addEventListener('click', () => {
      const approval = approvalUrlFrom(record.response);
      $('#receipt-description').textContent = approval
        ? `Delivered to ${record.endpoint} · HTTP ${record.status}. Approve the verified purchase here: ${approval}`
        : `Delivered to ${record.endpoint} · HTTP ${record.status}. Delivery does not mean the order has been approved.`;
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

function renderConfigs() {
  $('#config-company-name').hidden = currentKind !== 'users';
  const profiles = currentKind === 'users' ? companyEmployees() : state.companies;
  const cards = profiles.map(profile => {
    const card = document.createElement('article');
    card.className = 'config-card';
    const description = currentKind === 'users'
      ? [profile.config.role, profile.config.department].filter(Boolean).join(' · ')
      : profile.config.industry;
    card.append(textElement('div', initials(profile.label), 'config-avatar'), textElement('h2', profile.label), textElement('p', description || 'Custom configuration'));
    const actions = textElement('div', '', 'config-actions');
    const edit = textElement('button', 'Edit profile', 'text-button');
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
  $('#config-dialog-title').textContent = editingId ? 'Edit profile' : 'New profile';
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
    userConfig: structuredClone(activeProfile('users')?.config || {}),
    companyConfig: structuredClone(activeProfile('companies').config),
  };
}

function updatePreview() {
  $('#payload-preview').textContent = JSON.stringify(buildPayload(), null, 2);
  $('#send-request').disabled = !state.active.users;
}

function openRequest() {
  if (!state) return;
  pendingRequest = { id: crypto.randomUUID(), createdAt: new Date().toISOString() };
  $('#request-text').value = '';
  const user = activeProfile('users');
  const company = activeProfile('companies');
  $('#request-avatar').textContent = initials(user?.config.name || user?.label);
  $('#request-person').textContent = user?.config.name || user?.label || 'No employee selected';
  $('#request-organization').textContent = `${company.config.name || company.label} · ${user?.config.role || 'Employee'}`;
  feedback('#request-feedback', '');
  updatePreview();
  $('#request-dialog').showModal();
  $('#request-text').focus();
}

function approvalUrlFrom(responseText) {
  if (typeof responseText !== 'string' || !responseText.trim()) return null;
  try {
    const body = JSON.parse(responseText);
    return body?.engine?.approval_url || body?.approval_url || null;
  } catch {
    return null;
  }
}

function openConnection() {
  $('#service-url').value = state.endpoint;
  $('#service-token').value = token;
  feedback('#service-feedback', '');
  $('#service-dialog').showModal();
}

function updateAccountPreview() {
  const user = activeProfile('users', $('#account-user').value);
  $('#account-avatar').textContent = initials(user?.config.name || user?.label);
  $('#account-preview-name').textContent = user?.config.name || user?.label || 'No employee profiles';
  $('#account-preview-role').textContent = user
    ? [user.config.role, user.config.department].filter(Boolean).join(' · ')
    : 'Add an employee configuration for this company first.';
  $('#save-account').disabled = !user;
}

function openAccount() {
  if (!state) return;
  populateSelect('#account-company', 'companies');
  populateSelect('#account-user', 'users');
  updateAccountPreview();
  feedback('#account-feedback', '');
  renderConfigs();
  $('#account-dialog').showModal();
}

document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
document.querySelectorAll('[data-open-account]').forEach(button => button.addEventListener('click', openAccount));
$('#overview-nav').addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
document.querySelectorAll('[data-kind]').forEach(button => button.addEventListener('click', () => {
  currentKind = button.dataset.kind;
  document.querySelectorAll('[data-kind]').forEach(tab => {
    tab.classList.toggle('selected', tab === button);
    tab.setAttribute('aria-pressed', String(tab === button));
  });
  renderConfigs();
}));
$('#new-config').addEventListener('click', () => openConfig());
$('#account-company').addEventListener('change', () => {
  populateSelect('#account-user', 'users', $('#account-user').value, $('#account-company').value);
  updateAccountPreview();
});
$('#account-user').addEventListener('change', updateAccountPreview);
$('#account-form').addEventListener('submit', event => {
  event.preventDefault();
  const companyId = $('#account-company').value;
  const userId = $('#account-user').value;
  if (!companyEmployees(companyId).some(user => user.id === userId)) {
    feedback('#account-feedback', 'Choose an employee belonging to this company.');
    return;
  }
  state.active = { companies: companyId, users: userId };
  persist();
  renderContext();
  renderHistory();
  renderConfigs();
  $('#account-dialog').close();
  notify('Account updated.');
});
$('#request-order').addEventListener('click', openRequest);
$('#request-settings').addEventListener('click', openConnection);
$('#request-text').addEventListener('input', updatePreview);

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
    renderHistory();
    renderConfigs();
    $('#config-dialog').close();
    notify('Configuration saved.');
  } catch (error) { feedback('#config-feedback', `Could not save: ${error.message}`); }
});

$('#request-dialog').addEventListener('cancel', event => { if (sending) event.preventDefault(); });
$('#request-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (sending) return;
  if (!state.active.users) return feedback('#request-feedback', 'Choose an employee in Account settings before sending.');
  if (!$('#request-text').value.trim()) return feedback('#request-feedback', 'Describe what you would like to order.');
  if (!state.endpoint) {
    feedback('#request-feedback', 'Add your order service URL before sending.');
    openConnection();
    return;
  }
  const payload = buildPayload();
  const endpoint = state.endpoint;
  const userLabel = activeProfile('users').label;
  const companyLabel = activeProfile('companies').label;
  sending = true;
  $('#request-form').querySelectorAll('button, input, textarea, select').forEach(element => { element.disabled = true; });
  $('#send-request').textContent = 'Sending…';
  feedback('#request-feedback', 'Sending your request and both profiles…', false);
  try {
    const response = await fetch('/api/requests', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ endpoint, token, payload }), signal: AbortSignal.timeout(120000),
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
    const approval = approvalUrlFrom(result.response);
    notify(approval ? `Request accepted — approve in the verifier: ${approval}` : 'Request sent to the order service.');
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
    if (!response.ok) throw new Error('Unable to load account profiles.');
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
      completedTasks: saved?.completedTasks && typeof saved.completedTasks === 'object' && !Array.isArray(saved.completedTasks) ? saved.completedTasks : {},
    };
    if (!token && typeof seeds.defaultToken === 'string') token = seeds.defaultToken;
    state.active = {};
    for (const kind of ['users', 'companies']) {
      const defaultId = kind === 'companies' && state.companies.some(item => item.id === 'northstar') ? 'northstar' : state[kind][0].id;
      state.active[kind] = state[kind].some(item => item.id === saved?.active?.[kind]) ? saved.active[kind] : defaultId;
    }
    renderContext();
    persist();
    renderHistory();
    renderConfigs();
  } catch (error) {
    feedback('#boot-error', `${error.message} Please reload the workspace.`);
  }
}
initialize();
