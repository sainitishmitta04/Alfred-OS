// Alfred OS voice overlay: hotkey → record → speech-to-text → orchestrator → card.
const { app, BrowserWindow, globalShortcut, ipcMain, Menu, Tray, nativeImage, screen, shell, systemPreferences } = require('electron');
const path = require('node:path');
const { PROVIDERS, resolveStt, parseYesNo } = require('./lib');

const ENV_PATH = path.join(__dirname, '..', '.env');
try { process.loadEnvFile(ENV_PATH); } catch { /* no .env yet: the tray and the card say what's missing */ }

const ORCH = (process.env.ORCHESTRATOR_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const HOTKEY = process.env.HOTKEY || 'Alt+Space';
const CONFIRM_TIMEOUT_MS = 45000;
const W = 460, H = 330;

let win, tray, health = null;
let recording = false;
let sttChoice = {};             // tray override, until restart
let pending = null;             // { session_id, card } while the orchestrator waits for yes / no
let queue = Promise.resolve();  // one command at a time: the next waits for the last to finish

const send = (type, data = {}) => win?.webContents.send('state', { type, ...data });
const offline = (e) => e?.cause?.code === 'ECONNREFUSED' || /fetch failed/.test(e?.message || '');

async function orch(route, body) {
  const r = await fetch(ORCH + route, {
    method: body ? 'POST' : 'GET',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(body ? 30000 : 3000),
  });
  if (!r.ok) throw new Error(`orchestrator ${r.status}: ${(await r.text()).slice(0, 160)}`);
  return r.json();
}

async function checkHealth() {
  try { health = await orch('/health'); } catch { health = null; }
  buildTray();
}

function currentStt() { try { return resolveStt(process.env, sttChoice); } catch { return null; } }

function buildTray() {
  if (!tray) { tray = new Tray(nativeImage.createEmpty()); tray.setTitle(' Alfred'); }
  const cur = currentStt();
  const sttItems = Object.entries(PROVIDERS).flatMap(([id, p]) => p.models.map((model) => ({
    label: `${p.label} · ${model}${process.env[p.keyEnv] ? '' : '  (no key)'}`,
    type: 'radio',
    enabled: Boolean(process.env[p.keyEnv]),
    checked: Boolean(cur && cur.provider === id && cur.model === model),
    click: () => { sttChoice = { provider: id, model }; buildTray(); },
  })));
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: health ? `Orchestrator online · ${health.agents.join(', ')}` : `Orchestrator offline (${ORCH})`, enabled: false },
    { label: `${HOTKEY.replace('Alt', '⌥')} to talk, again to send · Esc cancels`, enabled: false },
    { type: 'separator' },
    { label: 'Speech-to-text (until restart)', submenu: sttItems },
    { label: 'Check orchestrator', click: checkHealth },
    { label: 'Open .env', click: () => shell.openPath(ENV_PATH) },
    { type: 'separator' },
    { label: 'Quit Alfred', role: 'quit' },
  ]));
}

function createWindow() {
  const { workArea: wa } = screen.getPrimaryDisplay();
  win = new BrowserWindow({
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
  win.setAlwaysOnTop(true, 'screen-saver');
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  win.setIgnoreMouseEvents(true, { forward: true }); // clicks pass through, except over the card's buttons
  win.loadFile('index.html');
  win.once('ready-to-show', () => win.showInactive()); // never steal focus from the app you're using
}

function setRecording(on, cancel = false) {
  recording = on;
  if (on) globalShortcut.register('Escape', () => setRecording(false, true)); // Esc is ours only while recording
  else globalShortcut.unregister('Escape');
  win.webContents.send('record', { on, cancel });
}

function show(res, heard, stt, sttMs) {
  const card = { heard, stt, sttMs, ...res };
  if (res.status === 'needs_confirmation') {
    pending = { session_id: res.session_id, card };
    const id = res.session_id;
    setTimeout(() => { if (pending?.session_id === id) queue = queue.then(() => answer(false, 'No answer')); }, CONFIRM_TIMEOUT_MS);
    return send('confirm', card);
  }
  pending = null;
  send('result', card);
}

async function answer(approved, heard) {
  const p = pending;
  if (!p) return;
  pending = null;
  send('thinking', { heard: `${p.card.heard} → ${heard || (approved ? 'Yes' : 'No')}` });
  try {
    show(await orch('/confirm', { session_id: p.session_id, approved }), p.card.heard, p.card.stt, p.card.sttMs);
  } catch (e) {
    send('error', { heard: p.card.heard, message: offline(e) ? 'Orchestrator offline' : e.message });
  }
}

async function handleTake(audio, mimeType, ms) {
  if (ms < 300 || audio.length < 1000) return send('idle', { note: 'Too short' });
  let stt;
  try { stt = resolveStt(process.env, sttChoice); } catch (e) { return send('error', { message: e.message, hint: 'Fix it in .env' }); }
  if (!stt.key) return send('error', { message: `No ${PROVIDERS[stt.provider].keyEnv} in .env`, hint: 'Add it and restart, or pick another provider in the tray' });

  send('transcribing', { stt: stt.label });
  const t0 = Date.now();
  let text;
  try {
    text = await PROVIDERS[stt.provider].transcribe({
      audio, mimeType, model: stt.model, language: stt.language, key: stt.key,
      baseUrl: process.env.DEEPGRAM_BASE_URL || undefined,
    });
  } catch (e) {
    return send('error', { message: `Speech-to-text failed: ${e.message}`, hint: 'Check the key, or switch provider in the tray' });
  }
  const sttMs = Date.now() - t0;
  if (!text) return send('idle', { note: "Didn't catch that" });

  if (pending) { // this take answers the orchestrator's question
    const approved = parseYesNo(text);
    if (approved === null) return send('confirm', { ...pending.card, note: `Heard "${text}". Say yes or no.` });
    return answer(approved, text);
  }

  send('thinking', { heard: text, stt: stt.label, sttMs });
  try {
    show(await orch('/transcript', { transcript: text }), text, stt.label, sttMs);
  } catch (e) {
    send('error', {
      heard: text,
      message: offline(e) ? 'Orchestrator offline' : e.message,
      hint: offline(e) ? 'Start it: uv run uvicorn orchestrator.main:app --port 8000' : '',
    });
    checkHealth();
  }
}

ipcMain.handle('take', (_e, { audio, mimeType, ms }) => {
  queue = queue.then(() => handleTake(Buffer.from(audio), mimeType, ms)).catch((e) => send('error', { message: e.message }));
  return queue;
});
ipcMain.handle('answer', (_e, approved) => { queue = queue.then(() => answer(approved)); return queue; });
ipcMain.on('interactive', (_e, on) => win?.setIgnoreMouseEvents(!on, { forward: true }));

app.whenReady().then(() => {
  app.dock?.hide(); // menu-bar app
  if (process.platform === 'darwin') systemPreferences.askForMediaAccess('microphone').catch(() => {});
  createWindow();
  if (!globalShortcut.register(HOTKEY, () => setRecording(!recording))) {
    console.error(`Could not register ${HOTKEY}: another app owns it. Set HOTKEY in .env (e.g. Control+Alt+Space).`);
  }
  buildTray();
  checkHealth();
  // Dev only: run a recorded file through the real pipeline (STT → orchestrator → card) without the mic.
  if (process.env.ALFRED_PREVIEW_WAV) {
    win.webContents.once('did-finish-load', () =>
      setTimeout(() => handleTake(require('node:fs').readFileSync(process.env.ALFRED_PREVIEW_WAV), 'audio/wav', 2000), 800));
  }
});
app.on('will-quit', () => globalShortcut.unregisterAll());
app.on('window-all-closed', () => { /* keep running in the menu bar */ });
