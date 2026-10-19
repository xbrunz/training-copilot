// Unit tests for the maker's request builder and reply parser.
const test = require('node:test');
const assert = require('node:assert');
const { buildMakerRequest, parseMakerResponse } = require('../workflows/code/maker.js');

const ok = (text, extra = {}) => ({
  model: 'claude-haiku-5-5', stop_reason: 'end_turn', usage: { input_tokens: 100, output_tokens: 20 },
  content: [{ type: 'text', text }], ...extra,
});

test('first attempt: no rejection feedback; schema-constrained, low effort', () => {
  const body = buildMakerRequest({ planned: { sport: 'run' } }, []);
  assert.strictEqual(body.model, 'claude-haiku-5-5');
  assert.strictEqual(body.output_config.format.type, 'json_schema');
  assert.strictEqual(body.output_config.effort, 'low');
  assert.ok(!body.messages[0].content.includes('rejected'));
});

test('retry: quotes each rejected proposal and its reasons', () => {
  const attempts = [{ attempt: 1, proposal: { sport: 'run', intensity: 'hard' },
    verdict: { passed: false, violations: [{ rule_id: 'R2_short_sleep', message: 'Slept 4.8 h' }] } }];
  const msg = buildMakerRequest({}, attempts).messages[0].content;
  assert.ok(msg.includes('Attempt 1') && msg.includes('Slept 4.8 h') && msg.includes('corrected'));
});

test('valid reply: proposal and token usage', () => {
  const r = parseMakerResponse(ok('{"sport":"rest"}'));
  assert.deepStrictEqual(r.proposal, { sport: 'rest' });
  assert.strictEqual(r.input_tokens, 100);
  assert.strictEqual(r.error, null);
});

test('refusal, truncation, invalid JSON, empty response: no proposal, explicit error, tokens kept', () => {
  const cases = [
    [ok('', { stop_reason: 'refusal', stop_details: { category: 'general_harms' } }), /Refused \(general_harms\)/],
    [ok('{"sport":', { stop_reason: 'max_tokens' }), /max_tokens/],
    [ok('not json'), /not valid JSON/],
    [{}, /No message/],
  ];
  for (const [resp, err] of cases) {
    const r = parseMakerResponse(resp);
    assert.strictEqual(r.proposal, null);
    assert.match(r.error, err);
  }
  assert.strictEqual(parseMakerResponse(cases[0][0]).output_tokens, 20); // refused calls still cost tokens
});
