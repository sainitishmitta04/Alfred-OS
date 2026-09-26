// Shared by the overlay (renderer.js) and the Tasks window (tasks.js): how a task, its steps and its chips look.
const ICONS = {
  ok: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
  fail: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>',
  neutral: '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="4"/></svg>',
};

const ROUTERS = { jev: 'Jev', jev_low_confidence: 'Jev', claude_fallback: 'Claude', keyword: 'Keywords' };

// Step actions as people read them. Browser MCP tools arrive as "playwright__browser_click" and similar.
const STEP_LABELS = {
  route: 'Routed', destructive_check: 'Flagged as risky', confirmation_requested: 'Asked you',
  confirmation_received: 'You answered', dispatch: 'Started', resume: 'Resumed', result: 'Result',
  jev_verify: 'Checked the result', error: 'Error',
  plan: 'Planning', subtask: 'Sub-task', think: 'Thinking', finish: 'Finished', ask_user: 'Question for you',
  answer: 'Answer', synthesize: 'Summary', jev_risk_check: 'Risk check', jev_review: 'Reviewed the step',
  web_search: 'Searching the web', fetch_url: 'Reading a page', llm_unavailable: 'Model unavailable', budget: 'Out of time',
  desktop_request: 'Sent to the desktop agent', desktop_unreachable: 'Desktop agent not running',
  desktop_not_configured: 'Desktop agent not configured', desktop_timeout: 'Desktop agent timed out',
  execute_system_script: 'System action', control_media_player: 'Music', headless_web_scrape: 'Reading a page',
};

function stepLabel(action = '') {
  if (STEP_LABELS[action]) return STEP_LABELS[action];
  const tool = action.replace(/^[a-z0-9]+__/, '').replace(/^browser_/, '').replace(/_/g, ' ');
  return tool.charAt(0).toUpperCase() + tool.slice(1);
}

const ms = (n) => (n >= 1000 ? `${(n / 1000).toFixed(1)} s` : `${Math.round(n)} ms`);

// [text, className] pairs for a task's route and latencies.
function taskChips(t) {
  const out = [];
  if (t.route) {
    const conf = typeof t.route_confidence === 'number' ? ` · ${t.route_confidence.toFixed(2)}` : '';
    out.push([`${t.route}${t.route_source ? ` · ${ROUTERS[t.route_source] || t.route_source}` : ''}${conf}`, 'route']);
  }
  if (t.sttMs) out.push([`STT ${t.stt} · ${ms(t.sttMs)}`]);
  if (t.jev_latency_ms != null) out.push([`${ROUTERS[t.route_source] || 'Router'} ${ms(t.jev_latency_ms)}`]);
  if (t.agent_latency_ms != null) out.push([`agent ${ms(t.agent_latency_ms)}`]);
  if (t.latency_ms != null) out.push([`total ${ms((t.sttMs || 0) + t.latency_ms)}`]);
  return out;
}

function chipEls(chips) {
  return chips.map(([text, cls]) => Object.assign(document.createElement('span'), { className: `chip ${cls || ''}`, textContent: text }));
}

function stepEls(steps) {
  return steps.map((st) => {
    const li = document.createElement('li');
    const state = st.success === true || st.success === 1 ? 'ok' : st.success === false || st.success === 0 ? 'fail' : 'neutral';
    li.innerHTML = ICONS[state]; // static SVG only; step text goes in via textContent
    li.firstChild.classList.add(state);
    const text = document.createElement('span');
    const b = document.createElement('b');
    b.textContent = stepLabel(st.action);
    text.append(b, st.detail ? ` ${st.detail}` : '');
    text.title = `${st.action}${st.detail ? `: ${st.detail}` : ''}`;
    li.append(text);
    return li;
  });
}

const firstLine = (text = '') => text.split('\n').find((l) => l.trim()) || '';
