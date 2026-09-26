// The overlay: records while the hotkey is on, draws the card for every state main.js sends.
const $ = (sel) => document.querySelector(sel);
const pill = $('#pill'), label = $('#pill .label'), card = $('#card');
const bars = [...document.querySelectorAll('.bar')];
const RELEASE_TAIL_MS = 150; // keep recording briefly after the second tap so the last syllable isn't cut off

let rec = null, ctx = null, startedAt = 0, hideTimer = 0;
let asking = null;  // session id of the question the card shows
let gen = 0;      // bumps on every hotkey on/off, so a start() still waiting for the mic knows it was overtaken
let live = false; // recording now: status updates about the previous take must not repaint the pill

// Pill updates about a take in flight; skipped while a new recording owns the pill.
const status = (state, text) => { if (!live) setPill(state, text); };

// ---------- recording ----------
alfred.onRecord(({ on, cancel }) => { gen++; on ? start() : stop(cancel); });

async function start() {
  const my = gen;
  live = true;
  if (!card.classList.contains('confirm')) clearCard(); // a pending question stays on screen
  setPill('listening', '⌥Space to send · Esc to cancel');
  let s;
  try {
    s = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  } catch {
    if (my !== gen) return;
    live = false;
    alfred.stopped(); // main still thinks we're recording and holds Esc
    setPill('idle');
    return render({ kind: 'error', answer: 'Microphone blocked', hint: 'Allow Electron in System Settings → Privacy & Security → Microphone.' });
  }
  ctx ||= new AudioContext();
  await ctx.resume();
  // Tapped again while the mic was opening: release it rather than record with nobody tracking it.
  if (my !== gen) return s.getTracks().forEach((t) => t.stop());

  const analyser = ctx.createAnalyser();
  analyser.fftSize = 512;
  ctx.createMediaStreamSource(s).connect(analyser);
  const chunks = [];
  rec = new MediaRecorder(s, { mimeType: 'audio/webm;codecs=opus' });
  rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  Object.assign(rec, { chunks, stopMeter: meter(analyser) }); // rec.stream (read-only, built in) is `s`
  rec.start(100);
  startedAt = performance.now();
}

function stop(cancelled) {
  live = false;
  if (!rec) return setPill('idle'); // stopped before the mic opened; start() releases it
  const r = rec, ms = performance.now() - startedAt;
  rec = null;
  setTimeout(() => {
    r.onstop = async () => {
      r.stream.getTracks().forEach((t) => t.stop()); // mic indicator off
      r.stopMeter();
      if (cancelled) return status('idle');
      status('busy', 'Sending…');
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
  let frame = 0, raf = 0;
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
  return () => { // each recording stops only its own loop
    cancelAnimationFrame(raf);
    if (!live) bars.forEach((b) => (b.style.transform = 'scaleY(0.15)'));
  };
}

// ---------- states from main ----------
// Tasks run in the background: the overlay only says "On it", tells you when one is done, and holds a question
// on screen while a task waits for your yes or no. Everything else lives in the Tasks window.
alfred.onState((s) => {
  switch (s.type) {
    case 'transcribing': return status('busy', `Transcribing · ${s.stt}`);
    case 'accepted':
      status('idle');
      render({ kind: 'toast', heard: s.transcript, answer: s.note || 'On it', chips: taskChips(s) });
      return autoHide(2500);
    case 'done':
      status('idle');
      render({
        kind: `toast ${s.status === 'failed' ? 'error' : ''}`, heard: s.transcript,
        answer: firstLine(s.response_text) || (s.status === 'cancelled' ? 'Cancelled' : 'Done'),
        chips: taskChips(s), hint: 'Click for all tasks',
      });
      return autoHide(6000);
    case 'confirm':
      status('idle');
      asking = s.session_id;
      return render({
        kind: 'confirm', heard: s.transcript, answer: s.response_text, steps: (s.steps || []).slice(-4),
        chips: taskChips(s), actions: true,
        hint: [s.note, s.more ? `${s.more} more waiting` : '', 'Or tap ⌥Space and say "yes" or "no".'].filter(Boolean).join(' · '),
      });
    case 'error':
      status('idle');
      render({ kind: 'error', heard: s.heard, answer: s.message, hint: s.hint });
      return autoHide(15000);
    case 'idle':
      status('idle');
      if (s.note) { render({ answer: s.note }); autoHide(2500); }
  }
});

function setPill(state, text = '') {
  pill.className = `pill ${state}`;
  label.textContent = text;
}

function render({ kind = '', heard = '', answer = '', hint = '', steps = [], chips = [], actions = false }) {
  clearTimeout(hideTimer);
  if (!kind.includes('confirm')) asking = null;
  card.className = `card ${kind}`;
  card.hidden = false;
  card.querySelector('.heard').textContent = heard ? `“${heard}”` : '';
  card.querySelector('.answer').textContent = answer;
  card.querySelector('.hint').textContent = hint;
  card.querySelector('.steps').replaceChildren(...stepEls(steps));
  card.querySelector('.chips').replaceChildren(...chipEls(chips));
  card.querySelector('.actions').hidden = !actions;
}

function autoHide(after) {
  clearTimeout(hideTimer);
  hideTimer = setTimeout(() => {
    card.classList.add('leaving');
    setTimeout(() => { card.hidden = true; card.classList.remove('leaving'); alfred.interactive(false); }, 130);
  }, after);
}

function clearCard() { clearTimeout(hideTimer); card.hidden = true; alfred.interactive(false); }

// ---------- clicks: the card is click-through except while the pointer is over it ----------
function reply(approved) {
  if (!asking) return;
  card.querySelector('.actions').hidden = true;
  alfred.answer(asking, approved);
}
card.querySelector('.yes').addEventListener('click', (e) => { e.stopPropagation(); reply(true); });
card.querySelector('.no').addEventListener('click', (e) => { e.stopPropagation(); reply(false); });
card.addEventListener('click', () => { if (card.classList.contains('toast')) { clearCard(); alfred.openTasks(); } });
card.addEventListener('mouseenter', () => alfred.interactive(true));
card.addEventListener('mouseleave', () => alfred.interactive(false));
