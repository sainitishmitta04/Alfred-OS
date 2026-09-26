const test = require('node:test');
const assert = require('node:assert/strict');
const { PROVIDERS, resolveStt, parseYesNo, sseParser, applyEvent, taskFromSession } = require('../lib');

test('live events: split across chunks, keepalives skipped, bad JSON ignored', () => {
  const got = [];
  const push = sseParser((type, data) => got.push([type, data]));
  push(': connected\n\nevent: session\ndata: {"session_id":"s1","transcr');
  push('ipt":"lower the volume"}\n\n: keepalive\n\nevent: status\ndata: {broken\n\n');
  push('event: step\r\ndata: {"session_id":"s1","step":{"id":7,"action":"route"}}\r\n\r\n');
  assert.deepEqual(got.map(([t]) => t), ['session', 'step']);
  assert.equal(got[0][1].transcript, 'lower the volume');
});

test('tasks: events build one task per session; steps are not duplicated', () => {
  const tasks = new Map();
  applyEvent(tasks, 'session', { type: 'session', session_id: 's1', transcript: 'lower the volume' });
  applyEvent(tasks, 'status', { type: 'status', session_id: 's1', status: 'routed', route: 'direct' });
  const step = { id: 3, action: 'dispatch' };
  applyEvent(tasks, 'step', { type: 'step', session_id: 's1', step });
  applyEvent(tasks, 'step', { type: 'step', session_id: 's1', step });
  const t = applyEvent(tasks, 'status', { type: 'status', session_id: 's1', status: 'completed', response_text: 'Done.' });
  assert.equal(t.status, 'completed');
  assert.equal(t.route, 'direct');
  assert.equal(t.type, undefined); // the event's own "type" field doesn't leak into the task
  assert.equal(t.steps.length, 1);
  assert.equal(applyEvent(tasks, 'status', { status: 'x' }), null);
});

test('history rows keep what live events already knew', () => {
  const prev = { session_id: 's1', steps: [{ id: 1 }], created: 5, sttMs: 400 };
  const t = taskFromSession({ id: 's1', status: 'completed', created_at: '2026-09-26 09:00:00' }, prev);
  assert.equal(t.session_id, 's1');
  assert.equal(t.sttMs, 400);
  assert.equal(t.steps.length, 1);
  assert.equal(t.created, 5);
  assert.equal(taskFromSession({ id: 's2', created_at: '2026-09-26 09:00:00' }).created, Date.parse('2026-09-26T09:00:00Z'));
});

test('spoken confirmation: only a whole yes or no answers; anything else asks again', () => {
  assert.equal(parseYesNo('Yes, go ahead.'), true);
  assert.equal(parseYesNo('yeah do it'), true);
  assert.equal(parseYesNo('Okay.'), true);
  assert.equal(parseYesNo('No.'), false);
  assert.equal(parseYesNo("don't do it"), false);
  assert.equal(parseYesNo('Don’t do it.'), false); // curly apostrophe from the transcriber
  assert.equal(parseYesNo('No thanks'), false);
  // New commands that happen to contain yes/no words are not answers.
  assert.equal(parseYesNo('okay, open Safari'), null);
  assert.equal(parseYesNo('sure, play music'), null);
  assert.equal(parseYesNo('make sure the lights are off'), null);
  assert.equal(parseYesNo('stop the music'), null);
  assert.equal(parseYesNo('yes... no, stop'), null);
  assert.equal(parseYesNo('what was that?'), null);
});

test('provider and model: tray choice, then .env, then the default model', () => {
  assert.deepEqual(
    (({ provider, model, language }) => ({ provider, model, language }))(resolveStt({})),
    { provider: 'deepgram', model: 'nova-3', language: 'en' },
  );
  const env = { STT_PROVIDER: 'openai', STT_MODEL: 'whisper-1', OPENAI_API_KEY: 'k', STT_LANGUAGE: '' };
  assert.equal(resolveStt(env).model, 'whisper-1');
  assert.equal(resolveStt(env).key, 'k');
  assert.equal(resolveStt(env).language, '');
  assert.equal(resolveStt(env, { provider: 'deepgram' }).model, 'nova-3'); // .env model belongs to openai, not deepgram
  assert.equal(resolveStt(env, { provider: 'deepgram', model: 'nova-2' }).model, 'nova-2');
  assert.throws(() => resolveStt({ STT_PROVIDER: 'nope' }), /Unknown STT_PROVIDER/);
});

const fakeFetch = (reply, seen) => async (url, init) => {
  seen.url = String(url); seen.init = init;
  return { ok: true, status: 200, json: async () => reply, text: async () => '' };
};

test('deepgram: opts out of model improvement and reads the transcript', async () => {
  const seen = {};
  const text = await PROVIDERS.deepgram.transcribe({
    audio: Buffer.from('x'), mimeType: 'audio/webm', model: 'nova-3', language: 'en', key: 'k',
    fetchFn: fakeFetch({ results: { channels: [{ alternatives: [{ transcript: ' Lower the volume. ' }] }] } }, seen),
  });
  assert.equal(text, 'Lower the volume.');
  assert.match(seen.url, /^https:\/\/api\.in\.deepgram\.com\/v1\/listen\?/); // India endpoint by default
  assert.match(seen.url, /model=nova-3/);
  assert.match(seen.url, /mip_opt_out=true/);
  assert.equal(seen.init.headers.Authorization, 'Token k');
});

test('openai: sends the model and reads the text', async () => {
  const seen = {};
  const text = await PROVIDERS.openai.transcribe({
    audio: Buffer.from('x'), mimeType: 'audio/webm', model: 'gpt-4o-mini-transcribe', language: '', key: 'k',
    fetchFn: fakeFetch({ text: 'Open Safari.' }, seen),
  });
  assert.equal(text, 'Open Safari.');
  assert.equal(seen.init.body.get('model'), 'gpt-4o-mini-transcribe');
  assert.equal(seen.init.body.get('language'), null);
});

test('a vendor error is reported, not swallowed', async () => {
  const fetchFn = async () => ({ ok: false, status: 401, text: async () => 'bad key' });
  await assert.rejects(
    PROVIDERS.deepgram.transcribe({ audio: Buffer.from('x'), mimeType: 'audio/webm', model: 'nova-3', key: 'k', fetchFn }),
    /Deepgram 401: bad key/,
  );
});
