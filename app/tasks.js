// The Tasks window: every command, newest first, updated live from the orchestrator's events (via main.js).
const list = document.getElementById('list');
const empty = document.getElementById('empty');
const summary = document.getElementById('summary');
const tasks = new Map();
const open = new Set();       // expanded rows
const loading = new Set();    // detail requests in flight
const FINAL = new Set(['completed', 'failed', 'cancelled']);
// A task still "running" this long has really failed (a crash, or the orchestrator restarted): show it as failed,
// not a spinner. Agent commands finish in seconds; the browser agent is capped at 120s, so 3 min is safely past.
const STUCK_MS = 3 * 60 * 1000;

const STATES = {
  running: { mark: 'running', text: 'Running' },
  waiting: { mark: 'waiting', text: 'Needs you' },
  completed: { mark: 'ok', text: 'Done' },
  failed: { mark: 'fail', text: 'Failed' },
  cancelled: { mark: 'neutral', text: 'Cancelled' },
  expired: { mark: 'neutral', text: 'Question expired' },
};

function stateOf(t) {
  if (FINAL.has(t.status)) return t.status;
  const stuck = Date.now() - t.created > STUCK_MS;
  if (t.status === 'needs_confirmation') return stuck ? 'expired' : 'waiting';
  return stuck ? 'failed' : 'running'; // a task that never reached a terminal status has failed, not "running"
}

const clock = (t) => new Date(t.created).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
function timing(t, state) {
  if (state === 'running' || state === 'waiting') {
    const s = Math.floor((Date.now() - t.created) / 1000);
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }
  return t.latency_ms != null ? `${clock(t)} · ${ms(t.latency_ms)}` : clock(t);
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function row(t) {
  const state = stateOf(t);
  const li = el('li', `task ${state}${open.has(t.session_id) ? ' open' : ''}`);
  const head = el('button', 'task-head');
  head.type = 'button';
  head.setAttribute('aria-expanded', String(open.has(t.session_id)));
  const mark = el('span', `mark ${STATES[state].mark}`);
  mark.title = STATES[state].text;
  mark.setAttribute('aria-label', STATES[state].text);
  const body = el('span', 'task-main');
  body.append(el('span', 'task-title', t.transcript || '…'));
  const last = t.steps?.[t.steps.length - 1];
  const sub = state === 'failed' && !FINAL.has(t.status) ? (firstLine(t.response_text) || 'Stopped before it finished')
    : state === 'waiting' || state === 'expired' || FINAL.has(state) ? firstLine(t.response_text)
    : last ? `${stepLabel(last.action)}${last.detail ? ` — ${last.detail}` : ''}` : 'Starting…';
  body.append(el('span', 'task-sub', sub));
  const meta = el('span', 'task-meta');
  if (t.route) meta.append(el('span', 'chip route', t.route));
  meta.append(el('span', 'task-time', timing(t, state)));
  head.append(mark, body, meta);
  head.addEventListener('click', () => toggle(t.session_id));
  li.append(head);

  if (open.has(t.session_id)) {
    const detail = el('div', 'task-detail');
    if (t.response_text) detail.append(el('p', `answer${state === 'failed' ? ' failed' : ''}`, t.response_text));
    if (state === 'waiting') {
      const actions = el('div', 'actions');
      const yes = el('button', 'btn yes', 'Yes, do it');
      const no = el('button', 'btn no', 'No');
      yes.type = no.type = 'button';
      yes.addEventListener('click', () => { actions.replaceChildren(el('span', 'muted', 'Sent')); alfred.answer(t.session_id, true); });
      no.addEventListener('click', () => { actions.replaceChildren(el('span', 'muted', 'Sent')); alfred.answer(t.session_id, false); });
      actions.append(yes, no);
      detail.append(actions);
    }
    const steps = el('ol', 'steps');
    steps.append(...stepEls(t.steps || []));
    detail.append(steps);
    const chips = el('div', 'chips');
    chips.append(...chipEls(taskChips(t)));
    detail.append(chips);
    li.append(detail);
  }
  return li;
}

function draw() {
  const rows = [...tasks.values()].sort((a, b) => b.created - a.created);
  empty.hidden = rows.length > 0;
  const counts = rows.reduce((c, t) => ((c[stateOf(t)] = (c[stateOf(t)] || 0) + 1), c), {});
  summary.textContent = [counts.running && `${counts.running} running`, counts.waiting && `${counts.waiting} waiting for you`]
    .filter(Boolean).join(' · ') || (rows.length ? 'Nothing running' : '');
  list.replaceChildren(...rows.map(row));
}

function toggle(id) {
  if (open.has(id)) open.delete(id); else open.add(id);
  const t = tasks.get(id);
  // History rows arrive without steps: load them the first time a row opens.
  if (open.has(id) && t && !t.steps?.length && !loading.has(id)) {
    loading.add(id);
    alfred.taskDetail(id).then((full) => { if (full) tasks.set(id, full); loading.delete(id); draw(); });
  }
  draw();
}

alfred.tasks().then((all) => { all.forEach((t) => tasks.set(t.session_id, t)); draw(); });
alfred.onTask((t) => { tasks.set(t.session_id, t); draw(); });
setInterval(() => { if ([...tasks.values()].some((t) => !FINAL.has(t.status))) draw(); }, 1000); // tick timers
