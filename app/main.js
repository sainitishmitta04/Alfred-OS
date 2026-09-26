// Alfred OS: hotkey → record → speech-to-text → a background task on the orchestrator → overlay toasts + Tasks window.
const { app, BrowserWindow, globalShortcut, ipcMain, Menu, Tray, nativeImage, screen, shell, systemPreferences } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { PROVIDERS, resolveStt, parseYesNo, sseParser, applyEvent, taskFromSession, FINAL } = require('./lib');

const ROOT = path.join(__dirname, '..');
const ENV_PATH = path.join(ROOT, '.env');
try { process.loadEnvFile(ENV_PATH); } catch { /* no .env yet: the tray and the card say what's missing */ }

const ORCH = (process.env.ORCHESTRATOR_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const DESKTOP = (process.env.DESKTOP_AGENT_URL || 'http://127.0.0.1:8787').replace(/\/$/, '');
const HOTKEY = process.env.HOTKEY || 'Alt+Space';
const W = 460, H = 330;

let overlay, tasksWin, tray, quitting = false;
let health = { orchestrator: null, desktop: null };
let recording = false;
let sttChoice = {};               // tray override, until restart
let takes = Promise.resolve();    // takes are transcribed in order; the tasks they start run in parallel
const tasks = new Map();          // session_id → task: history from GET /sessions, kept live by /events
const mine = new Set();           // tasks started from this app get a "done" toast
const answering = new Set();      // questions already answered, so a double answer can't send two

const send = (type, data = {}) => overlay?.webContents.send('state', { type, ...data });
const offline = (e) => e?.cause?.code === 'ECONNREFUSED' || /fetch failed/.test(e?.message || '');

async function orch(route, body) {
  const r = await fetch(ORCH + route, {
    method: body ? 'POST' : 'GET',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(10000), // every call answers at once now; the work itself runs in the background
  });
  if (!r.ok) {
    const err = new Error(`orchestrator ${r.status}: ${(await r.text()).slice(0, 160)}`);
    err.status = r.status;
    throw err;
  }
  return r.json();
}

// ---------- tasks ----------
// Questions older than this are expired: never offered again, so a "yes" can't re-run an old destructive command
// (after an orchestrator restart, approving one starts the whole task over).
const QUESTION_TTL_MS = 10 * 60 * 1000;
const waiting = () => [...tasks.values()]
  .filter((t) => t.status === 'needs_confirmation' && !answering.has(t.session_id) && Date.now() - t.created < QUESTION_TTL_MS)
  .sort((a, b) => a.created - b.created);

// The oldest question stays on the overlay until it's answered. Returns false when nothing is waiting.
function showQuestion(note) {
  const [first, ...rest] = waiting();
  if (!first) return false;
  send('confirm', { ...first, note, more: rest.length });
  return true;
}

// While a question waits, keep it on screen, so no take can answer a card the user can't see.
function notice(type, data) {
  if (!showQuestion([data.message || data.note, 'Say "yes" or "no".'].filter(Boolean).join(' '))) send(type, data);
}

function publish(t, before) {
  tasksWin?.webContents.send('tasks:update', t);
  updateTrayTitle();
  if (t.status === 'needs_confirmation' && before !== 'needs_confirmation') return showQuestion();
  if (FINAL.has(t.status) && !FINAL.has(before)) {
    answering.delete(t.session_id);
    if (!showQuestion() && mine.has(t.session_id)) send('done', t);
  }
}

function onEvent(type, ev) {
  const before = tasks.get(ev?.session_id)?.status;
  const t = applyEvent(tasks, type, ev);
  if (t) publish(t, before);
}

async function resync() {
  try {
    for (const row of await orch('/sessions?limit=50')) {
      const prev = tasks.get(row.id);
      const t = taskFromSession(row, prev);
      tasks.set(row.id, t);
      if (prev?.status !== t.status) publish(t, prev?.status);
    }
  } catch { /* orchestrator not up yet */ }
}

// One live connection to the orchestrator's events, reconnecting with backoff; each reconnect resyncs history.
async function followEvents() {
  let delay = 1000;
  for (;;) {
    try {
      const r = await fetch(`${ORCH}/events`);
      if (!r.ok) throw new Error(`events ${r.status}`);
      delay = 1000;
      await resync();
      const push = sseParser(onEvent);
      const decoder = new TextDecoder();
      for await (const chunk of r.body) push(decoder.decode(chunk, { stream: true }));
    } catch { /* down or restarting */ }
    await new Promise((res) => setTimeout(res, delay));
    delay = Math.min(delay * 2, 5000);
  }
}

async function startTask(text, stt, sttMs) {
  let res;
  try {
    res = await orch('/tasks', { transcript: text });
  } catch (e) {
    checkHealth();
    return notice('error', {
      heard: text,
      message: offline(e) ? 'Orchestrator offline' : e.message,
      hint: offline(e) ? 'Start it: uv run uvicorn orchestrator.main:app --port 8000' : '',
    });
  }
  const id = res.session_id;
  // Events for this task can arrive before this reply does, so merge rather than replace.
  const t = tasks.get(id) || { session_id: id, transcript: text, status: 'pending', steps: [], created: Date.now() };
  Object.assign(t, { transcript: t.transcript || text, stt, sttMs });
  tasks.set(id, t);
  mine.add(id);
  tasksWin?.webContents.send('tasks:update', t);
  updateTrayTitle();
  if (FINAL.has(t.status)) return showQuestion() || send('done', t); // it already finished (fast failures do)
  if (!showQuestion()) send('accepted', t);
}

async function answer(id, approved) {
  const t = tasks.get(id);
  if (answering.has(id) || !waiting().includes(t)) return; // already answered, or expired
  answering.add(id);
  publish(t, t?.status);
  try {
    await orch(`/tasks/${id}/confirm`, { approved });
  } catch (e) {
    if (e.status === 409) return; // already answered from the other window
    answering.delete(id);
    return send('error', { heard: t?.transcript, message: offline(e) ? 'Orchestrator offline' : e.message });
  }
  if (!showQuestion()) send('accepted', { ...t, note: approved ? 'Going ahead' : 'Cancelling' });
}

async function handleTake(audio, mimeType, ms) {
  if (ms < 300 || audio.length < 1000) return notice('idle', { note: 'Too short' });
  let stt;
  try { stt = resolveStt(process.env, sttChoice); } catch (e) { return notice('error', { message: e.message, hint: 'Fix it in .env' }); }
  if (!stt.key) return notice('error', { message: `No ${PROVIDERS[stt.provider].keyEnv} in .env`, hint: 'Add it and restart, or pick another provider in the tray' });

  send('transcribing', { stt: stt.label });
  const t0 = Date.now();
  let text;
  try {
    text = await PROVIDERS[stt.provider].transcribe({
      audio, mimeType, model: stt.model, language: stt.language, key: stt.key,
      baseUrl: process.env.DEEPGRAM_BASE_URL || undefined,
    });
  } catch (e) {
    return notice('error', { message: `Speech-to-text failed: ${e.message}`, hint: 'Check the key, or switch provider in the tray' });
  }
  const sttMs = Date.now() - t0;
  if (!text) return notice('idle', { note: "Didn't catch that" });

  // A pure yes or no answers the question on screen; anything else is a new task, and the question stays.
  const [question] = waiting();
  const approved = question ? parseYesNo(text) : null;
  if (approved !== null) return answer(question.session_id, approved);
  return startTask(text, stt.label, sttMs);
}

// ---------- backends: start the orchestrator and the desktop service if they aren't running ----------
const UV = process.env.UV_BIN || ['/opt/homebrew/bin/uv', '/usr/local/bin/uv'].find((p) => fs.existsSync(p)) || 'uv';
const SERVICES = [
  { key: 'orchestrator', name: 'Orchestrator', url: ORCH, cwd: ROOT, ours: (h) => Array.isArray(h?.agents),
    args: ['run', 'uvicorn', 'orchestrator.main:app', '--host', '127.0.0.1', '--port', new URL(ORCH).port || '8000'] },
  { key: 'desktop', name: 'Desktop agent', url: DESKTOP, cwd: path.join(ROOT, 'desktop-use', 'backend'),
    ours: (h) => Array.isArray(h?.tools),
    args: ['run', '--env-file', ENV_PATH, 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', new URL(DESKTOP).port || '8787'] },
];

async function probe(url) {
  try { return await (await fetch(`${url}/health`, { signal: AbortSignal.timeout(1500) })).json(); } catch { return null; }
}
// A port can be answered by some other app: only a /health that looks like ours counts as up.
async function isUp(s) { return s.ours(await probe(s.url)); }

async function startServices() {
  if (process.env.ALFRED_START_BACKENDS === 'false') return;
  for (const s of SERVICES) {
    const h = await probe(s.url);
    if (s.ours(h)) continue;
    if (h) { console.error(`${s.name}: ${s.url} is answered by another app; set a free port in .env`); continue; }
    const log = fs.openSync(path.join(app.getPath('userData'), `${s.key}.log`), 'a');
    s.proc = spawn(UV, s.args, { cwd: s.cwd, stdio: ['ignore', log, log], env: process.env });
    s.proc.on('error', (e) => console.error(`${s.name} did not start (${UV}): ${e.message}`));
    s.proc.on('exit', () => { s.proc = null; checkHealth(); });
  }
}

// ---------- tray, windows ----------
async function checkHealth() {
  const [o, d] = await Promise.all(SERVICES.map((s) => probe(s.url)));
  health = {
    orchestrator: SERVICES[0].ours(o) ? o : null, desktop: SERVICES[1].ours(d) ? d : null,
    clash: [o && !SERVICES[0].ours(o) && ORCH, d && !SERVICES[1].ours(d) && DESKTOP].filter(Boolean),
  };
  buildTray();
}

function updateTrayTitle() {
  if (!tray) return;
  const running = [...tasks.values()].filter((t) => mine.has(t.session_id) && !FINAL.has(t.status) && t.status !== 'needs_confirmation').length;
  const asking = waiting().length;
  tray.setTitle(` Alfred${running ? ` · ${running} running` : ''}${asking ? ` · ${asking} waiting` : ''}`);
}

function currentStt() { try { return resolveStt(process.env, sttChoice); } catch { return null; } }

function buildTray() {
  if (!tray) tray = new Tray(nativeImage.createEmpty());
  updateTrayTitle();
  const cur = currentStt();
  const sttItems = Object.entries(PROVIDERS).flatMap(([id, p]) => p.models.map((model) => ({
    label: `${p.label} · ${model}${process.env[p.keyEnv] ? '' : '  (no key)'}`,
    type: 'radio',
    enabled: Boolean(process.env[p.keyEnv]),
    checked: Boolean(cur && cur.provider === id && cur.model === model),
    click: () => { sttChoice = { provider: id, model }; buildTray(); },
  })));
  const { orchestrator: o, desktop: d, clash = [] } = health;
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Show tasks', click: showTasks },
    { type: 'separator' },
    ...clash.map((url) => ({ label: `${url} is used by another app: set a free port in .env`, enabled: false })),
    { label: o ? `Orchestrator online · ${o.agents.join(', ')}${o.jev ? ' · Jev' : ''}` : `Orchestrator offline (${ORCH})`, enabled: false },
    { label: d ? `Desktop agent online${d.anthropic_configured ? '' : ' · no Anthropic key'}` : `Desktop agent offline (${DESKTOP})`, enabled: false },
    { label: `${HOTKEY.replace('Alt', '⌥')} to talk, again to send · Esc cancels`, enabled: false },
    { type: 'separator' },
    { label: 'Speech-to-text (until restart)', submenu: sttItems },
    { label: 'Check services', click: checkHealth },
    { label: 'Open .env', click: () => shell.openPath(ENV_PATH) },
    { type: 'separator' },
    { label: 'Quit Alfred', role: 'quit' },
  ]));
}

function createOverlay() {
  const { workArea: wa } = screen.getPrimaryDisplay();
  overlay = new BrowserWindow({
    width: W, height: H,
    x: Math.round(wa.x + (wa.width - W) / 2), y: wa.y + wa.height - H - 8,
    frame: false, transparent: true, resizable: false, movable: false, fullscreenable: false,
    alwaysOnTop: true, skipTaskbar: true, hasShadow: false, show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      backgroundThrottling: false,
      autoplayPolicy: 'no-user-gesture-required', // a hotkey isn't a click in the page; the mic meter must still start
    },
  });
  overlay.setAlwaysOnTop(true, 'screen-saver');
  overlay.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  overlay.setIgnoreMouseEvents(true, { forward: true }); // clicks pass through, except over the card
  overlay.loadFile('index.html');
  overlay.once('ready-to-show', () => overlay.showInactive()); // never steal focus from the app you're using
}

function showTasks() {
  if (!tasksWin) {
    tasksWin = new BrowserWindow({
      width: 560, height: 700, minWidth: 420, minHeight: 360, title: 'Alfred — Tasks',
      backgroundColor: '#0B0D10', show: false,
      webPreferences: { preload: path.join(__dirname, 'preload.js') },
    });
    tasksWin.loadFile('tasks.html');
    tasksWin.on('close', (e) => { if (!quitting) { e.preventDefault(); tasksWin.hide(); } });
    tasksWin.once('ready-to-show', () => tasksWin.show());
  } else {
    tasksWin.show();
  }
  app.focus({ steal: true });
}

function setRecording(on, cancel = false) {
  recording = on;
  if (on) globalShortcut.register('Escape', () => setRecording(false, true)); // Esc is ours only while recording
  else globalShortcut.unregister('Escape');
  overlay.webContents.send('record', { on, cancel });
}

// ---------- IPC ----------
ipcMain.handle('take', (_e, { audio, mimeType, ms }) => {
  takes = takes.then(() => handleTake(Buffer.from(audio), mimeType, ms)).catch((e) => send('error', { message: e.message }));
  return takes;
});
ipcMain.handle('answer', (_e, id, approved) => answer(id, approved));
ipcMain.handle('tasks:all', () => [...tasks.values()].sort((a, b) => b.created - a.created));
ipcMain.handle('tasks:detail', async (_e, id) => {
  try {
    const t = taskFromSession(await orch(`/sessions/${id}`), tasks.get(id));
    tasks.set(id, t);
    return t;
  } catch { return tasks.get(id) || null; }
});
ipcMain.on('tasks:open', showTasks);
ipcMain.on('interactive', (_e, on) => overlay?.setIgnoreMouseEvents(!on, { forward: true }));
// The page couldn't open the mic: stop recording here too, so Esc is released and the next tap starts fresh.
ipcMain.on('stopped', () => { recording = false; globalShortcut.unregister('Escape'); });

app.whenReady().then(async () => {
  app.dock?.hide(); // menu-bar app
  if (process.platform === 'darwin') systemPreferences.askForMediaAccess('microphone').catch(() => {});
  createOverlay();
  if (!globalShortcut.register(HOTKEY, () => setRecording(!recording))) {
    console.error(`Could not register ${HOTKEY}: another app owns it. Set HOTKEY in .env (e.g. Control+Alt+Space).`);
  }
  buildTray();
  await startServices();
  checkHealth();
  setInterval(checkHealth, 15000);
  followEvents();
  if (process.env.ALFRED_SHOW_TASKS) showTasks();
  // Dev only: run a recorded file through the real pipeline (STT → orchestrator → card) without the mic.
  if (process.env.ALFRED_PREVIEW_WAV) {
    for (let i = 0; i < 120 && !(await isUp(SERVICES[0])); i++) await new Promise((res) => setTimeout(res, 500));
    handleTake(fs.readFileSync(process.env.ALFRED_PREVIEW_WAV), 'audio/wav', 2000);
  }
});
app.on('before-quit', () => { quitting = true; });
app.on('will-quit', () => {
  globalShortcut.unregisterAll();
  for (const s of SERVICES) s.proc?.kill(); // only the ones this app started
});
app.on('window-all-closed', () => { /* keep running in the menu bar */ });
