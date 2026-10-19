// Builds the "daily context": the only data the maker agent ever sees.
// Pure function, so live API data and sample scenarios go through the same code.
// Data minimisation: numbers and categories only. No names, activity titles,
// GPS, device IDs or timestamps beyond the date.

function buildContext({ targetDate, source, scenarioId, wellness, activities, weather, plan }) {
  const addDays = (iso, n) => {
    const d = new Date(iso + 'T12:00:00Z');
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  };
  const isNum = (v) => typeof v === 'number' && Number.isFinite(v) && v !== 0;
  const round = (v, dp = 1) => (v == null ? null : Math.round(v * 10 ** dp) / 10 ** dp);
  const mean = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);

  // "today" is the day the workflow runs (the evening before targetDate)
  const today = addDays(targetDate, -1);
  const byDate = Object.fromEntries((wellness || []).map((r) => [r.id, r]));
  const todayRow = byDate[today] || {};
  const prior7 = [1, 2, 3, 4, 5, 6, 7].map((i) => byDate[addDays(today, -i)]).filter(Boolean);

  // --- Recovery: today vs own 7-day baseline (baseline excludes today)
  const hrvBase = mean(prior7.map((r) => r.hrv).filter(isNum));
  const rhrBase = mean(prior7.map((r) => r.restingHR).filter(isNum));
  const hrv = isNum(todayRow.hrv) ? todayRow.hrv : null;
  const rhr = isNum(todayRow.restingHR) ? todayRow.restingHR : null;
  const recovery = {
    hrv_ms: hrv,
    hrv_baseline_7d_ms: round(hrvBase),
    hrv_vs_baseline_pct: hrv && hrvBase ? round((hrv / hrvBase - 1) * 100) : null,
    resting_hr_bpm: rhr,
    resting_hr_baseline_7d_bpm: round(rhrBase),
    resting_hr_vs_baseline_bpm: rhr && rhrBase ? round(rhr - rhrBase) : null,
    sleep_hours: isNum(todayRow.sleepSecs) ? round(todayRow.sleepSecs / 3600) : null,
    sleep_score: isNum(todayRow.sleepScore) ? todayRow.sleepScore : null,
  };

  // --- Load: fitness/fatigue from the latest row that has them, plus 7d vs previous 7d
  const latestLoadRow = [todayRow, ...prior7].find((r) => isNum(r.ctl) && isNum(r.atl)) || {};
  const acts = (activities || []).map((a) => ({
    date: String(a.start_date_local || '').slice(0, 10),
    sport: a.type,
    load: Number(a.icu_training_load) || 0,
  }));
  const inWindow = (a, fromBack, toBack) => a.date >= addDays(today, -toBack) && a.date <= addDays(today, -fromBack);
  const last7 = acts.filter((a) => inWindow(a, 0, 6));
  const prev7 = acts.filter((a) => inWindow(a, 7, 13));
  const sum = (xs) => xs.reduce((s, a) => s + a.load, 0);
  const activeDays = new Set(last7.map((a) => a.date));
  let daysSinceRest = 0;
  while (daysSinceRest < 14 && acts.some((a) => a.date === addDays(today, -daysSinceRest))) daysSinceRest++;
  const load7 = sum(last7);
  const loadPrev7 = sum(prev7);
  const load = {
    ctl: round(latestLoadRow.ctl),
    atl: round(latestLoadRow.atl),
    tsb: latestLoadRow.ctl != null ? round(latestLoadRow.ctl - latestLoadRow.atl) : null,
    load_7d: round(load7, 0),
    load_prev_7d: round(loadPrev7, 0),
    load_change_pct: loadPrev7 > 0 ? round((load7 / loadPrev7 - 1) * 100) : null,
    sessions_7d: last7.length,
    rest_days_7d: 7 - activeDays.size,
    days_since_rest: daysSinceRest,
    trained_today: activeDays.has(today),
  };

  // --- Weather for the target date (Open-Meteo daily block)
  const d = (weather && weather.daily) || {};
  const idx = (d.time || []).indexOf(targetDate);
  const pick = (k) => (idx >= 0 && d[k] ? d[k][idx] : null);
  const weatherOut = {
    temp_min_c: pick('temperature_2m_min'),
    temp_max_c: pick('temperature_2m_max'),
    precip_mm: pick('precipitation_sum'),
    precip_probability_pct: pick('precipitation_probability_max'),
    wind_max_kmh: pick('wind_speed_10m_max'),
    gust_max_kmh: pick('wind_gusts_10m_max'),
  };

  // --- Plan for the target weekday
  const weekday = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'][new Date(targetDate + 'T12:00:00Z').getUTCDay()];
  const planned = (plan && plan.week && plan.week[weekday]) || null;

  // --- Data quality: lets the guardrails act conservatively when data is missing
  const missingToday = Object.entries({ hrv, resting_hr: rhr, sleep_hours: recovery.sleep_hours })
    .filter(([, v]) => v == null)
    .map(([k]) => k);
  const dataQuality = {
    wellness_days_7d: [0, 1, 2, 3, 4, 5, 6].filter((i) => isNum((byDate[addDays(today, -i)] || {}).hrv)).length,
    missing_today: missingToday,
    activities_14d: acts.length, // 0 means "no data", not "fully rested"
    weather_available: idx >= 0,
    plan_available: planned != null,
  };

  return {
    target_date: targetDate,
    weekday,
    data_source: source,
    scenario_id: scenarioId || null,
    goal: plan ? plan.goal : null,
    phase: plan ? plan.phase : null,
    planned,
    recovery,
    load,
    weather: weatherOut,
    data_quality: dataQuality,
  };
}

if (typeof module !== 'undefined') module.exports = { buildContext };
