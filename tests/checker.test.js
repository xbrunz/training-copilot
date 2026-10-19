// Unit tests for the deterministic checker and the safe fallback.
// Run: docker run --rm -v "$PWD":/work:ro -w /work --entrypoint node docker.n8n.io/n8nio/n8n:2.44.4 --test tests/
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const { checkProposal, safeFallback } = require('../workflows/code/checker.js');
const { buildContext } = require('../workflows/code/build_context.js');

// ARBITRARY TEST VALUES: they exist only to exercise each rule's logic.
// They are not training recommendations; real values live in config/guardrails.json.
const T = {
  rules: {
    R1_hrv_drop: { hrv_below_baseline_pct: 10 },
    R2_short_sleep: { min_sleep_hours: 6 },
    R3_elevated_rhr: { rhr_above_baseline_bpm: 5 },
    R4_fatigue: { min_tsb: -20 },
    R5_load_ramp: { max_load_increase_pct: 30 },
    R6_rest_overdue: { max_days_without_rest: 10 },
    R7_duration_cap: { max_duration_vs_plan: 1.5 },
    R8_weather: { max_precip_mm: 5, max_gust_kmh: 50 },
    R9_missing_data: { max_intensity: 'easy' },
    R10_planned_rest: { enforce: true },
  },
};
const ctx = (over = {}) => ({
  planned: { sport: 'run', duration_min: 50, intensity: 'hard', location: 'outdoor' },
  recovery: { hrv_vs_baseline_pct: 0, sleep_hours: 7.5, resting_hr_vs_baseline_bpm: 0 },
  load: { tsb: 0, load_change_pct: 0, days_since_rest: 1 },
  weather: { precip_mm: 0, gust_max_kmh: 20 },
  data_quality: { missing_today: [] },
  ...over,
});
const hardRun = { sport: 'run', duration_min: 50, intensity: 'hard', location: 'outdoor' };
const easyRun = { ...hardRun, intensity: 'easy' };
const ids = (res) => res.violations.map((v) => v.rule_id);

test('normal day: hard session passes', () => {
  const res = checkProposal(hardRun, ctx(), T);
  assert.deepStrictEqual(res, { passed: true, violations: [], not_configured: [] });
});

const cases = [
  ['R1_hrv_drop', { recovery: { hrv_vs_baseline_pct: -15 } }, hardRun, easyRun],
  ['R2_short_sleep', { recovery: { sleep_hours: 5 } }, hardRun, easyRun],
  ['R3_elevated_rhr', { recovery: { resting_hr_vs_baseline_bpm: 8 } }, { ...hardRun, intensity: 'moderate' }, easyRun],
  ['R4_fatigue', { load: { tsb: -25 } }, { ...hardRun, intensity: 'moderate' }, easyRun],
  ['R5_load_ramp', { load: { load_change_pct: 60 } }, hardRun, { ...hardRun, intensity: 'moderate' }],
  ['R6_rest_overdue', { load: { days_since_rest: 12 } }, { ...hardRun, intensity: 'moderate' }, easyRun],
  ['R7_duration_cap', {}, { ...easyRun, duration_min: 90 }, { ...easyRun, duration_min: 70 }],
  ['R8_weather', { weather: { precip_mm: 12, gust_max_kmh: 20 }, planned: { sport: 'bike', duration_min: 150, location: 'outdoor' } },
    { sport: 'bike', duration_min: 150, intensity: 'easy', location: 'outdoor' },
    { sport: 'bike', duration_min: 150, intensity: 'easy', location: 'trainer' }],
  ['R9_missing_data', { data_quality: { missing_today: ['hrv'] } }, { ...hardRun, intensity: 'moderate' }, easyRun],
  ['R10_planned_rest', { planned: { sport: 'rest', duration_min: 0 } }, easyRun,
    { sport: 'rest', duration_min: 0, intensity: 'easy', location: 'none' }],
];
for (const [rule, over, bad, good] of cases) {
  test(`${rule}: rejects the violating proposal, accepts the compliant one`, () => {
    const c = ctx(over);
    const rejected = checkProposal(bad, c, T);
    assert.strictEqual(rejected.passed, false);
    assert.ok(ids(rejected).includes(rule), `expected ${rule}, got ${ids(rejected)}`);
    assert.ok(rejected.violations.every((v) => v.message.length > 0));
    assert.strictEqual(checkProposal(good, c, T).passed, true, `${rule} should accept the compliant proposal`);
  });
}

test('rules do not fire when their signal is missing', () => {
  const c = ctx({ recovery: { hrv_vs_baseline_pct: null, sleep_hours: null, resting_hr_vs_baseline_bpm: null } });
  assert.strictEqual(checkProposal(hardRun, c, T).passed, true);
});

test('structural checks: vocabulary, location, rest shape, unparseable output', () => {
  assert.deepStrictEqual(ids(checkProposal({ ...hardRun, sport: 'yoga' }, ctx(), T)), ['S1_vocabulary']);
  assert.deepStrictEqual(ids(checkProposal({ ...easyRun, sport: 'swim' }, ctx(), T)), ['S2_location']);
  assert.ok(ids(checkProposal({ sport: 'rest', duration_min: 30, intensity: 'easy', location: 'none' }, ctx(), T)).includes('S3_rest_shape'));
  assert.deepStrictEqual(ids(checkProposal(null, ctx(), T)), ['S0_parse']);
});

test('unset thresholds are reported as not_configured, never as silent passes', () => {
  const real = JSON.parse(fs.readFileSync(__dirname + '/../config/guardrails.json'));
  const empty = { rules: Object.fromEntries(Object.keys(real.rules).map((k) => [k, {}])) };
  const res = checkProposal(hardRun, ctx(), empty);
  assert.strictEqual(res.passed, true);
  assert.deepStrictEqual(res.not_configured.sort(), Object.keys(real.rules).sort());
});

test('safe fallback passes the checker for every sample scenario', () => {
  const plan = JSON.parse(fs.readFileSync(__dirname + '/../data/plan/weekly_plan.json'));
  const dir = __dirname + '/../data/sample/scenarios/';
  for (const f of fs.readdirSync(dir)) {
    const s = JSON.parse(fs.readFileSync(dir + f));
    const c = buildContext({ targetDate: s.target_date, source: 'scenario', scenarioId: s.scenario_id,
      wellness: s.wellness, activities: s.activities, weather: s.weather, plan });
    const fb = safeFallback(c, T);
    assert.strictEqual(checkProposal(fb, c, T).passed, true, `${s.scenario_id}: ${JSON.stringify(fb)}`);
  }
});
