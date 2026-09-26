// Speech-to-text providers and the small pure helpers. Kept out of main.js so `npm test` runs without Electron.

const PROVIDERS = {
  deepgram: {
    label: 'Deepgram',
    keyEnv: 'DEEPGRAM_API_KEY',
    models: ['nova-3', 'nova-2'],
    // Default: Deepgram's India endpoint (inference in ap-south-2, Hyderabad). Same key as the global one.
    async transcribe({ audio, mimeType, model, language, key, baseUrl = 'https://api.in.deepgram.com', fetchFn = fetch }) {
      // mip_opt_out: keep this audio out of Deepgram's model-improvement programme.
      const q = new URLSearchParams({ model, smart_format: 'true', mip_opt_out: 'true' });
      if (language) q.set('language', language);
      const r = await fetchFn(`${baseUrl.replace(/\/$/, '')}/v1/listen?${q}`, {
        method: 'POST',
        headers: { Authorization: `Token ${key}`, 'Content-Type': mimeType },
        body: audio,
        signal: AbortSignal.timeout(15000),
      });
      if (!r.ok) throw new Error(`Deepgram ${r.status}: ${(await r.text()).slice(0, 160)}`);
      const j = await r.json();
      return (j?.results?.channels?.[0]?.alternatives?.[0]?.transcript || '').trim();
    },
  },
  openai: {
    label: 'OpenAI',
    keyEnv: 'OPENAI_API_KEY',
    models: ['gpt-4o-mini-transcribe', 'gpt-4o-transcribe', 'whisper-1'],
    async transcribe({ audio, mimeType, model, language, key, fetchFn = fetch }) {
      const form = new FormData();
      form.append('file', new Blob([audio], { type: mimeType }), 'take.webm');
      form.append('model', model);
      if (language) form.append('language', language);
      const r = await fetchFn('https://api.openai.com/v1/audio/transcriptions', {
        method: 'POST',
        headers: { Authorization: `Bearer ${key}` },
        body: form,
        signal: AbortSignal.timeout(15000),
      });
      if (!r.ok) throw new Error(`OpenAI ${r.status}: ${(await r.text()).slice(0, 160)}`);
      return ((await r.json()).text || '').trim();
    },
  },
};

// Which provider and model this take uses: the tray choice wins, then .env, then the provider's first model.
function resolveStt(env, choice = {}) {
  const envProvider = env.STT_PROVIDER || 'deepgram';
  const provider = choice.provider || envProvider;
  const p = PROVIDERS[provider];
  if (!p) throw new Error(`Unknown STT_PROVIDER "${provider}" (use ${Object.keys(PROVIDERS).join(' or ')})`);
  const model = choice.model || (provider === envProvider && env.STT_MODEL) || p.models[0];
  return { provider, model, language: env.STT_LANGUAGE ?? 'en', key: env[p.keyEnv] || '', label: `${p.label} ${model}` };
}

// A spoken answer to "should I go ahead?". Only a whole answer counts: "okay, open Safari" is a new
// command, not a yes, so anything that isn't purely yes or no returns null and the question is asked again.
const YES = /^(yes|yeah|yep|yup|sure|ok|okay|confirm|approve|go ahead|do it)( (please|go ahead|do it|confirm|sure|ok|okay))*$/;
const NO = /^(no|nope|nah|don't|dont|do not|stop|cancel|abort|decline)( (thanks|thank you|please|no|don't|dont|do it|stop|cancel))*$/;

function parseYesNo(text) {
  const t = text.toLowerCase().replace(/[’‘]/g, "'").replace(/[^a-z' ]+/g, ' ').replace(/\s+/g, ' ').trim();
  if (NO.test(t)) return false;
  if (YES.test(t)) return true;
  return null;
}

// The orchestrator's GET /events stream: feed it text as it arrives; it calls onEvent(type, data) per event.
function sseParser(onEvent) {
  let buf = '';
  return (chunk) => {
    buf += chunk.replace(/\r\n/g, '\n');
    let end;
    while ((end = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, end);
      buf = buf.slice(end + 2);
      let type = 'message', data = '';
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) type = line.slice(6).trim();
        else if (line.startsWith('data:')) data += line.slice(5).trim();
      }
      if (!data) continue; // keepalive comments
      try { onEvent(type, JSON.parse(data)); } catch { /* one bad event must not end the stream */ }
    }
  };
}

const FINAL = new Set(['completed', 'failed', 'cancelled']);

// Fold one orchestrator event into its task (session). Returns the task, or null if the event isn't about one.
function applyEvent(tasks, type, ev) {
  const id = ev?.session_id;
  if (!id || !['session', 'status', 'step', 'error'].includes(type)) return null;
  const t = tasks.get(id) || { session_id: id, transcript: '', status: 'pending', steps: [], created: Date.now() };
  if (type === 'session') t.transcript = ev.transcript || t.transcript;
  if (type === 'status') {
    const { type: _type, session_id: _id, ...fields } = ev;
    Object.assign(t, fields);
  }
  if (type === 'step' && ev.step && !t.steps.some((s) => s.id === ev.step.id)) t.steps.push(ev.step);
  if (type === 'error') t.error = ev.message;
  tasks.set(id, t);
  return t;
}

// A row from GET /sessions, in the same shape the live events build.
function taskFromSession(row, prev) {
  return {
    ...prev, ...row, session_id: row.id,
    steps: row.steps || prev?.steps || [],
    created: prev?.created || Date.parse(`${String(row.created_at).replace(' ', 'T')}Z`) || Date.now(),
  };
}

module.exports = { PROVIDERS, resolveStt, parseYesNo, sseParser, applyEvent, taskFromSession, FINAL };
