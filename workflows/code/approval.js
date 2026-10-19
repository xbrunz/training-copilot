// Human-in-the-loop: the approval message and what each answer does.
// Nothing is scheduled until a human answers; no answer means no action.

const DECISIONS = ['approve', 'lighter', 'rest'];
const PRICE_PER_MTOK = { 'claude-haiku-5-5': { input: 0.1, output: 0.5 } }; // display only; Postgres model_pricing is the source of truth
const REST = { sport: 'rest', duration_min: 0, intensity: 'easy', location: 'none', focus: 'Rest day' };

function esc(s) {
  return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function runCost(attempts) {
  let input = 0, output = 0, usd = 0;
  for (const a of attempts) {
    const c = a.call || {};
    const p = PRICE_PER_MTOK[c.model];
    input += c.input_tokens || 0;
    output += c.output_tokens || 0;
    if (p) usd += ((c.input_tokens || 0) * p.input + (c.output_tokens || 0) * p.output) / 1e6;
  }
  return { input, output, usd };
}

function describe(s) {
  if (!s || s.sport === 'rest') return 'Rest';
  return `${s.sport} · ${s.duration_min} min · ${s.intensity} · ${s.location}`;
}

function formatApproval({ run, context, final, attempts }) {
  const p = final.proposal;
  const r = context.recovery, l = context.load, w = context.weather;
  const cost = runCost(attempts);
  const rejections = attempts.filter((a) => !a.verdict.passed).length;
  const lines = [
    `<b>Training Copilot · ${esc(run.target_date)} (${esc(context.weekday)})</b>`,
    run.data_source === 'scenario' ? `<i>Test scenario: ${esc(run.scenario_id)}</i>` : '',
    '',
    `<b>Proposed:</b> ${esc(describe(p))}`,
    p.sport !== 'rest' ? `<b>Focus:</b> ${esc(p.focus)}` : '',
    `<b>Planned:</b> ${esc(describe(context.planned))}`,
    '',
    `<b>Why:</b> ${esc(p.rationale)}`,
    '',
    `HRV ${r.hrv_vs_baseline_pct ?? 'n/a'}% vs baseline · RHR ${r.resting_hr_vs_baseline_bpm ?? 'n/a'} bpm · sleep ${r.sleep_hours ?? 'n/a'} h`,
    `TSB ${l.tsb ?? 'n/a'} · load ${l.load_change_pct ?? 'n/a'}% wk/wk · ${l.days_since_rest} days since rest`,
    `Weather: ${w.temp_min_c ?? '?'}–${w.temp_max_c ?? '?'}°C, rain ${w.precip_mm ?? '?'} mm, gusts ${w.gust_max_kmh ?? '?'} km/h`,
    '',
    final.origin === 'fallback'
      ? `⚠️ <b>Safe fallback</b> (agent failed after ${attempts.length} attempt${attempts.length > 1 ? 's' : ''})`
      : `✅ Passed guardrails${rejections ? ` after ${rejections} rejection${rejections > 1 ? 's' : ''}` : ''}`,
    `<i>${attempts.length} LLM call${attempts.length > 1 ? 's' : ''} · ${cost.input}+${cost.output} tokens · $${cost.usd.toFixed(5)}</i>`,
  ];
  return lines.filter((x, i, a) => x !== '' || a[i - 1] !== '').join('\n').trim();
}

// Buttons are links to this execution's signed resume URL
function approvalButtons(resumeUrl) {
  const sep = resumeUrl.includes('?') ? '&' : '?';
  const labels = { approve: '✅ Approve', lighter: '🪶 Lighter', rest: '😴 Rest' };
  return DECISIONS.map((d) => ({ text: labels[d], url: `${resumeUrl}${sep}decision=${d}` }));
}

const STEP_DOWN = { hard: 'moderate', moderate: 'easy' };

// Deterministic: the human picks, code applies. "Lighter" = one intensity level
// down; an easy session becomes rest.
function applyDecision(decision, proposal) {
  if (decision == null) return { decision: 'no_response', session: null, origin: null };
  if (!DECISIONS.includes(decision)) throw new Error(`Unknown decision: ${decision}`);
  if (decision === 'approve') return { decision, session: proposal, origin: null };
  if (decision === 'rest' || proposal.sport === 'rest' || !STEP_DOWN[proposal.intensity]) {
    return { decision, session: { ...REST }, origin: 'human_rest' };
  }
  return {
    decision,
    session: { ...proposal, intensity: STEP_DOWN[proposal.intensity], focus: `${proposal.focus} (lighter)` },
    origin: 'human_lighter',
  };
}

if (typeof module !== 'undefined') module.exports = { formatApproval, approvalButtons, applyDecision, runCost, DECISIONS };
