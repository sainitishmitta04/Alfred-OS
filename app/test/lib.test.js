const test = require('node:test');
const assert = require('node:assert/strict');
const { PROVIDERS, resolveStt, parseYesNo } = require('../lib');

test('spoken confirmation: yes, no, and a muddled answer lands on no', () => {
  assert.equal(parseYesNo('Yes, go ahead.'), true);
  assert.equal(parseYesNo('yeah do it'), true);
  assert.equal(parseYesNo('No.'), false);
  assert.equal(parseYesNo("don't"), false);
  assert.equal(parseYesNo('yes... no, stop'), false);
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
