// Checker: deterministic guardrails over the maker's proposal.
// No LLM involved. Every rule returns a reason, so each rejection is explainable
// and feeds back into the maker's retry. Thresholds come from config/guardrails.json.

const INTENSITY_RANK = { easy: 0, moderate: 1, hard: 2 };
const LOCATIONS = {
  swim: ['pool', 'open_water'],
  bike: ['outdoor', 'trainer'],
  run: ['outdoor', 'trainer'],
  strength: ['garage'],
  rest: ['none'],
};

function checkProposal(proposal, context, config) {
  const violations = [];
  const notConfigured = [];
  const fail = (rule_id, message) => violations.push({ rule_id, message });
  const rules = config.rules;
  const value = (ruleId, key) => {
    const v = rules[ruleId] ? rules[ruleId][key] : null;
    if (v == null && !notConfigured.includes(ruleId)) notConfigured.push(ruleId);
    return v;
  };

  // --- S: structural checks, always on
  if (!proposal || typeof proposal !== 'object') {
    return { passed: false, violations: [{ rule_id: 'S0_parse', message: 'No valid JSON proposal' }], not_configured: [] };
  }
  const p = proposal;
  if (!LOCATIONS[p.sport]) fail('S1_vocabulary', `Unknown sport "${p.sport}"`);
  if (!(p.intensity in INTENSITY_RANK)) fail('S1_vocabulary', `Unknown intensity "${p.intensity}"`);
  if (!Number.isInteger(p.duration_min) || p.duration_min < 0) fail('S1_vocabulary', 'duration_min must be a non-negative integer');
  if (violations.length) return { passed: false, violations, not_configured: [] };
  if (!LOCATIONS[p.sport].includes(p.location)) fail('S2_location', `${p.sport} cannot be done at "${p.location}"`);
  if (p.sport === 'rest' && (p.duration_min !== 0 || p.intensity !== 'easy')) fail('S3_rest_shape', 'Rest must have duration 0 and intensity easy');
  if (p.sport !== 'rest' && p.duration_min === 0) fail('S3_rest_shape', 'A training session needs a duration above 0');

  const isHard = p.intensity === 'hard';
  const easyOrRest = p.sport === 'rest' || p.intensity === 'easy';
  const r = context.recovery || {};
  const l = context.load || {};
  const w = context.weather || {};
  const planned = context.planned || {};

  // --- R: athlete-configured guardrails. A rule only fires when its signal is present.
  const hrvDrop = value('R1_hrv_drop', 'hrv_below_baseline_pct');
  if (hrvDrop != null && r.hrv_vs_baseline_pct != null && r.hrv_vs_baseline_pct < -hrvDrop && isHard)
    fail('R1_hrv_drop', `HRV is ${-r.hrv_vs_baseline_pct}% below baseline (limit ${hrvDrop}%): no hard session`);

  const minSleep = value('R2_short_sleep', 'min_sleep_hours');
  if (minSleep != null && r.sleep_hours != null && r.sleep_hours < minSleep && isHard)
    fail('R2_short_sleep', `Slept ${r.sleep_hours} h (minimum ${minSleep} h): no hard session`);

  const rhrUp = value('R3_elevated_rhr', 'rhr_above_baseline_bpm');
  if (rhrUp != null && r.resting_hr_vs_baseline_bpm != null && r.resting_hr_vs_baseline_bpm > rhrUp && !easyOrRest)
    fail('R3_elevated_rhr', `Resting HR is +${r.resting_hr_vs_baseline_bpm} bpm (limit +${rhrUp}): easy or rest only`);

  const minTsb = value('R4_fatigue', 'min_tsb');
  if (minTsb != null && l.tsb != null && l.tsb < minTsb && !easyOrRest)
    fail('R4_fatigue', `Form (TSB) is ${l.tsb} (minimum ${minTsb}): easy or rest only`);

  const maxRamp = value('R5_load_ramp', 'max_load_increase_pct');
  if (maxRamp != null && l.load_change_pct != null && l.load_change_pct > maxRamp && isHard)
    fail('R5_load_ramp', `Load is up ${l.load_change_pct}% week on week (limit ${maxRamp}%): no hard session`);

  const maxStreak = value('R6_rest_overdue', 'max_days_without_rest');
  if (maxStreak != null && l.days_since_rest != null && l.days_since_rest >= maxStreak && !easyOrRest)
    fail('R6_rest_overdue', `${l.days_since_rest} days without rest (limit ${maxStreak}): rest or easy only`);

  const maxDur = value('R7_duration_cap', 'max_duration_vs_plan');
  if (maxDur != null && planned.duration_min > 0 && p.duration_min > planned.duration_min * maxDur)
    fail('R7_duration_cap', `${p.duration_min} min exceeds ${maxDur} x planned ${planned.duration_min} min`);

  const maxRain = value('R8_weather', 'max_precip_mm');
  const maxGust = value('R8_weather', 'max_gust_kmh');
  const badWeather = (maxRain != null && w.precip_mm != null && w.precip_mm > maxRain)
    || (maxGust != null && w.gust_max_kmh != null && w.gust_max_kmh > maxGust);
  if (badWeather && p.sport === 'bike' && p.location === 'outdoor')
    fail('R8_weather', `Forecast ${w.precip_mm} mm rain, gusts ${w.gust_max_kmh} km/h: no outdoor ride`);

  const maxWhenMissing = value('R9_missing_data', 'max_intensity');
  const missing = (context.data_quality && context.data_quality.missing_today) || [];
  if (maxWhenMissing != null && missing.length && INTENSITY_RANK[p.intensity] > INTENSITY_RANK[maxWhenMissing])
    fail('R9_missing_data', `Missing today: ${missing.join(', ')}. Intensity capped at ${maxWhenMissing}`);

  const keepRest = value('R10_planned_rest', 'enforce');
  if (keepRest === true && planned.sport === 'rest' && p.sport !== 'rest')
    fail('R10_planned_rest', 'Planned rest day must stay rest');

  return { passed: violations.length === 0, violations, not_configured: notConfigured };
}

// Safe fallback when the maker fails or exhausts its retries: never an LLM output.
// Easy version of the planned session (indoors if it was an outdoor ride); rest if
// that still breaks a rule. Rest passes every rule by construction.
function safeFallback(context, config) {
  const rest = { sport: 'rest', duration_min: 0, intensity: 'easy', location: 'none',
    focus: 'Rest day', changed_from_plan: true, rationale: 'Safe fallback: rest.' };
  const planned = context.planned;
  if (!planned || planned.sport === 'rest') return { ...rest, changed_from_plan: false };
  const easy = {
    sport: planned.sport,
    duration_min: planned.duration_min,
    intensity: 'easy',
    location: planned.sport === 'bike' ? 'trainer' : planned.location,
    focus: `Easy ${planned.sport}`,
    changed_from_plan: true,
    rationale: 'Safe fallback: easy version of the planned session.',
  };
  return checkProposal(easy, context, config).passed ? easy : rest;
}

if (typeof module !== 'undefined') module.exports = { checkProposal, safeFallback };
