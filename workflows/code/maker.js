// Maker: builds the Claude request and parses the reply.
// The maker knows the guardrail *policy* in plain words but not the thresholds;
// the checker enforces the numbers. Each attempt is a fresh single-turn request
// (previous rejections are quoted in the prompt), so nothing depends on replaying
// earlier model output.

const MAKER_MODEL = 'claude-haiku-5-5';

const SYSTEM_PROMPT = `You plan tomorrow's single training session for an amateur triathlete preparing for an IRONMAN 70.3.

You receive a JSON "daily context": the planned session for tomorrow, recovery signals compared with the athlete's own 7-day baseline, recent training load, tomorrow's weather in Lisbon, and data-quality flags.

How to decide:
- Start from the planned session. Keep it unless the data gives a reason to change it.
- When recovery signals are worse than baseline (lower HRV, higher resting heart rate, short sleep), fatigue is high, load has ramped up quickly, or many days have passed without rest, reduce intensity first, then duration, and choose rest when several signals agree.
- When data is missing, be more conservative, not less.
- Bad weather for an outdoor ride: move it to the indoor trainer rather than skipping it.
- Never make a session longer or harder than planned.
- A rest day has duration 0, intensity "easy" and location "none".

Write "focus" as a short workout description (for example "6 x 3 min at threshold, 2 min easy"). Write "rationale" in at most two sentences, naming the signals that drove the decision. Set "changed_from_plan" to true if sport, duration, intensity or location differs from the plan.

Your proposal is checked by deterministic safety rules before a human approves it. If a previous proposal was rejected, the reasons are listed: fix them without changing anything else.`;

const PROPOSAL_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['sport', 'duration_min', 'intensity', 'location', 'focus', 'changed_from_plan', 'rationale'],
  properties: {
    sport: { type: 'string', enum: ['swim', 'bike', 'run', 'strength', 'rest'] },
    duration_min: { type: 'integer' },
    intensity: { type: 'string', enum: ['easy', 'moderate', 'hard'] },
    location: { type: 'string', enum: ['pool', 'open_water', 'outdoor', 'trainer', 'garage', 'none'] },
    focus: { type: 'string' },
    changed_from_plan: { type: 'boolean' },
    rationale: { type: 'string' },
  },
};

function buildMakerRequest(context, attempts) {
  let user = `Daily context:\n${JSON.stringify(context, null, 1)}`;
  const rejected = attempts.filter((a) => a.verdict && !a.verdict.passed);
  if (rejected.length) {
    user += '\n\nPrevious proposals were rejected by the safety checker:';
    for (const a of rejected) {
      user += `\n- Attempt ${a.attempt}: ${JSON.stringify(a.proposal)}\n  Reasons: ${a.verdict.violations.map((v) => v.message).join('; ')}`;
    }
    user += '\nPropose a corrected session.';
  }
  return {
    model: MAKER_MODEL,
    max_tokens: 4000,
    output_config: { effort: 'low', format: { type: 'json_schema', schema: PROPOSAL_SCHEMA } },
    system: SYSTEM_PROMPT,
    messages: [{ role: 'user', content: user }],
  };
}

// Never throws: an unusable reply becomes proposal=null with a reason,
// which the checker rejects as S0_parse and the loop treats like any rejection.
function parseMakerResponse(resp) {
  const usage = (resp && resp.usage) || {};
  const out = {
    proposal: null,
    stop_reason: resp ? resp.stop_reason : null,
    input_tokens: usage.input_tokens != null ? usage.input_tokens : null,
    output_tokens: usage.output_tokens != null ? usage.output_tokens : null,
    model: resp && resp.model ? resp.model : MAKER_MODEL,
    error: null,
  };
  if (!resp || !Array.isArray(resp.content)) {
    out.error = 'No message in response';
    return out;
  }
  if (resp.stop_reason === 'refusal') {
    out.error = `Refused (${(resp.stop_details && resp.stop_details.category) || 'no category'})`;
    return out;
  }
  if (resp.stop_reason === 'max_tokens') {
    out.error = 'Hit max_tokens before finishing';
    return out;
  }
  const text = resp.content.filter((b) => b.type === 'text').map((b) => b.text).join('');
  try {
    out.proposal = JSON.parse(text);
  } catch (e) {
    out.error = 'Reply was not valid JSON';
  }
  return out;
}

if (typeof module !== 'undefined') module.exports = { buildMakerRequest, parseMakerResponse, SYSTEM_PROMPT, PROPOSAL_SCHEMA, MAKER_MODEL };
