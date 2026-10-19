// Unit tests for the human-approval step.
const test = require('node:test');
const assert = require('node:assert');
const { formatApproval, approvalButtons, applyDecision, runCost } = require('../workflows/code/approval.js');

const hard = { sport: 'run', duration_min: 50, intensity: 'hard', location: 'outdoor', focus: 'Intervals', rationale: 'Good <recovery> & sleep' };

test('approve keeps the proposal unchanged', () => {
  assert.deepStrictEqual(applyDecision('approve', hard), { decision: 'approve', session: hard, origin: null });
});

test('lighter steps intensity down one level; easy becomes rest', () => {
  assert.strictEqual(applyDecision('lighter', hard).session.intensity, 'moderate');
  assert.strictEqual(applyDecision('lighter', { ...hard, intensity: 'moderate' }).session.intensity, 'easy');
  assert.strictEqual(applyDecision('lighter', { ...hard, intensity: 'easy' }).session.sport, 'rest');
  assert.strictEqual(applyDecision('lighter', hard).origin, 'human_lighter');
});

test('rest always gives a rest day; no answer means no session', () => {
  assert.deepStrictEqual(applyDecision('rest', hard).session.sport, 'rest');
  assert.deepStrictEqual(applyDecision(undefined, hard), { decision: 'no_response', session: null, origin: null });
});

test('unknown decisions are refused', () => {
  assert.throws(() => applyDecision('delete_everything', hard), /Unknown decision/);
});

test('buttons append the decision to the signed resume URL', () => {
  const [a] = approvalButtons('http://127.0.0.1:5678/webhook-waiting/7?signature=abc');
  assert.strictEqual(a.url, 'http://127.0.0.1:5678/webhook-waiting/7?signature=abc&decision=approve');
  assert.strictEqual(approvalButtons('http://x/w/7').length, 3);
});

test('message escapes model text and shows cost and origin', () => {
  const attempts = [{ verdict: { passed: false }, call: { model: 'claude-haiku-5-5', input_tokens: 1000, output_tokens: 200 } },
                    { verdict: { passed: true }, call: { model: 'claude-haiku-5-5', input_tokens: 1000, output_tokens: 200 } }];
  const text = formatApproval({
    run: { target_date: '2026-10-20', data_source: 'live' },
    context: { weekday: 'tue', planned: hard, recovery: {}, load: { days_since_rest: 1 }, weather: {} },
    final: { origin: 'agent', proposal: hard }, attempts,
  });
  assert.ok(text.includes('Good &lt;recovery&gt; &amp; sleep'));
  assert.ok(text.includes('after 1 rejection'));
  assert.ok(text.includes('$0.00040'));
  const c = runCost(attempts); assert.deepStrictEqual([c.input, c.output, c.usd.toFixed(6)], [2000, 400, '0.000400']);
});
