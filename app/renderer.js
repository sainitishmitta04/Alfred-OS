// The overlay: records while the hotkey is on, draws the card for every state main.js sends.
const $ = (sel) => document.querySelector(sel);
const pill = $('#pill'), label = $('#pill .label'), card = $('#card');
const bars = [...document.querySelectorAll('.bar')];
const RELEASE_TAIL_MS = 150; // keep recording briefly after the second tap so the last syllable isn't cut off

const ICONS = {
  ok: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
  fail: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>',
  neutral: '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="4"/></svg>',
};

let rec = null, stream = null, ctx = null, raf = 0, startedAt = 0, hideTimer = 0;

// ---------- recording ----------
alfred.onRecord(({ on, cancel }) => (on ? start() : stop(cancel)));

async function start() {
  clearCard();
  setPill('listening', '⌥Space to send · Esc to cancel');
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  } catch {
    setPill('idle');
    return render({ kind: 'error', answer: 'Microphone blocked', hint: 'Allow Electron in System Settings → Privacy & Security → Microphone.' });
  }
  ctx ||= new AudioContext();
  await ctx.resume();
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 512;
  ctx.createMediaStreamSource(stream).connect(analyser);

  const chunks = [];
  rec = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
  rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  rec.chunks = chunks;
  rec.start(100);
  startedAt = performance.now();
  meter(analyser);
}

function stop(cancelled) {
  if (!rec) return;
  const r = rec, s = stream, ms = performance.now() - startedAt;
  rec = null;
  setTimeout(() => {
    r.onstop = async () => {
      s.getTracks().forEach((t) => t.stop()); // mic indicator off
      cancelAnimationFrame(raf);
      bars.forEach((b) => (b.style.transform = 'scaleY(0.15)'));
      if (cancelled) return setPill('idle');
      setPill('busy', 'Sending…');
      const blob = new Blob(r.chunks, { type: 'audio/webm' });
      await alfred.take(await blob.arrayBuffer(), 'audio/webm', ms);
    };
    r.stop();
  }, cancelled ? 0 : RELEASE_TAIL_MS);
}

// The bars follow the stream being recorded, so they can't move for sound that isn't captured.
function meter(analyser) {
  const buf = new Uint8Array(analyser.fftSize);
  const hist = new Array(bars.length).fill(0);
  let frame = 0;
  const tick = () => {
    if (frame++ % 3 === 0) {
      analyser.getByteTimeDomainData(buf);
      let sum = 0;
      for (const v of buf) { const x = (v - 128) / 128; sum += x * x; }
      hist.push(Math.min(1, Math.sqrt(sum / buf.length) * 5));
      hist.shift();
      bars.forEach((b, i) => (b.style.transform = `scaleY(${0.15 + hist[i] * 0.85})`));
    }
    raf = requestAnimationFrame(tick);
  };
  tick();
}

// ---------- states from main ----------
alfred.onState((s) => {
  switch (s.type) {
    case 'transcribing': return setPill('busy', `Transcribing · ${s.stt}`);
    case 'thinking':
      setPill('busy', 'Thinking…');
      return render({ heard: s.heard, chips: s.sttMs ? [sttChip(s)] : [], skeleton: true });
    case 'result':
      setPill('idle');
      render({ kind: s.status === 'failed' ? 'error' : '', heard: s.heard, answer: s.response_text, steps: s.steps, chips: chips(s) });
      return autoHide(12000);
    case 'confirm':
      setPill('idle');
      return render({
        kind: 'confirm', heard: s.heard, answer: s.response_text, steps: s.steps, chips: chips(s), actions: true,
        hint: s.note || 'Or tap ⌥Space and say "yes" or "no".',
      });
    case 'error':
      setPill('idle');
      render({ kind: 'error', heard: s.heard, answer: s.message, hint: s.hint });
      return autoHide(15000);
    case 'idle':
      setPill('idle');
      if (s.note) { render({ answer: s.note }); autoHide(2500); }
  }
});

function setPill(state, text = '') {
  pill.className = `pill ${state}`;
  label.textContent = text;
}

function render({ kind = '', heard = '', answer = '', hint = '', steps = [], chips = [], actions = false, skeleton = false }) {
  clearTimeout(hideTimer);
  card.className = `card ${kind}`;
  card.hidden = false;
  card.querySelector('.heard').textContent = heard ? `“${heard}”` : '';
  card.querySelector('.answer').textContent = answer;
  card.querySelector('.hint').textContent = hint;

  const list = card.querySelector('.steps');
  list.replaceChildren(...(steps || []).slice(-6).map((st) => {
    const li = document.createElement('li');
    const state = st.success === true || st.success === 1 ? 'ok' : st.success === false || st.success === 0 ? 'fail' : 'neutral';
    li.innerHTML = ICONS[state]; // static SVG only; step text goes in via textContent below
    li.firstChild.classList.add(state);
    const text = document.createElement('span');
    const b = document.createElement('b');
    b.textContent = st.action;
    text.append(b, st.detail ? ` ${st.detail}` : '');
    li.append(text);
    return li;
  }));

  const row = card.querySelector('.chips');
  row.replaceChildren(...chips.map(([text, cls]) => {
    const c = document.createElement('span');
    c.className = `chip ${cls || ''}`;
    c.textContent = text;
    return c;
  }));
  if (skeleton) row.append(...[1, 2].map(() => Object.assign(document.createElement('span'), { className: 'chip skeleton' })));

  card.querySelector('.actions').hidden = !actions;
}

const ms = (n) => (n >= 1000 ? `${(n / 1000).toFixed(1)} s` : `${Math.round(n)} ms`);
const sttChip = (s) => [`STT ${s.stt} · ${ms(s.sttMs)}`];
const ROUTERS = { jev: 'Jev', jev_low_confidence: 'Jev', claude_fallback: 'Claude', keyword: 'Keywords' };

function chips(s) {
  const out = [];
  if (s.route) {
    const conf = typeof s.route_confidence === 'number' ? ` · ${s.route_confidence.toFixed(2)}` : '';
    out.push([`${s.route}${s.route_source ? ` · ${ROUTERS[s.route_source] || s.route_source}` : ''}${conf}`, 'route']);
  }
  if (s.sttMs) out.push(sttChip(s));
  if (s.jev_latency_ms != null) out.push([`${ROUTERS[s.route_source] || 'Router'} ${ms(s.jev_latency_ms)}`]);
  if (s.agent_latency_ms != null) out.push([`agent ${ms(s.agent_latency_ms)}`]);
  if (s.latency_ms != null) out.push([`total ${ms((s.sttMs || 0) + s.latency_ms)}`]);
  return out;
}

function autoHide(after) {
  clearTimeout(hideTimer);
  hideTimer = setTimeout(() => {
    card.classList.add('leaving');
    setTimeout(() => { card.hidden = true; card.classList.remove('leaving'); }, 130);
  }, after);
}

function clearCard() { clearTimeout(hideTimer); card.hidden = true; }

// ---------- confirmation buttons (the only clickable part of the overlay) ----------
card.querySelector('.yes').addEventListener('click', () => { card.querySelector('.actions').hidden = true; alfred.answer(true); });
card.querySelector('.no').addEventListener('click', () => { card.querySelector('.actions').hidden = true; alfred.answer(false); });
const actions = card.querySelector('.actions');
actions.addEventListener('mouseenter', () => alfred.interactive(true));
actions.addEventListener('mouseleave', () => alfred.interactive(false));
