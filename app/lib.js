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

module.exports = { PROVIDERS, resolveStt, parseYesNo };
