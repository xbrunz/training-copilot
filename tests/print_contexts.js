const fs = require('fs');
const { buildContext } = require('../workflows/code/build_context.js');
const plan = JSON.parse(fs.readFileSync(__dirname + '/../data/plan/weekly_plan.json'));
for (const f of fs.readdirSync(__dirname + '/../data/sample/scenarios').sort()) {
  const s = JSON.parse(fs.readFileSync(__dirname + '/../data/sample/scenarios/' + f));
  const c = buildContext({ targetDate: s.target_date, source: 'scenario', scenarioId: s.scenario_id,
    wellness: s.wellness, activities: s.activities, weather: s.weather, plan });
  const r = c.recovery, l = c.load, w = c.weather;
  console.log(`${s.scenario_id.padEnd(28)} ${c.weekday} ${c.planned.sport}/${c.planned.intensity} | hrv ${r.hrv_vs_baseline_pct}% rhr +${r.resting_hr_vs_baseline_bpm} sleep ${r.sleep_hours}h | tsb ${l.tsb} load ${l.load_change_pct}% rest7 ${l.rest_days_7d} dsr ${l.days_since_rest} | rain ${w.precip_mm} gust ${w.gust_max_kmh} | dq ${c.data_quality.wellness_days_7d}/7 miss[${c.data_quality.missing_today}]`);
}
if (process.argv[2]) console.log(JSON.stringify(buildContext({ targetDate: '2026-10-20', source: 'scenario', wellness: JSON.parse(fs.readFileSync(__dirname + '/../data/sample/scenarios/s01_good_recovery_intervals.json')).wellness, activities: [], weather: {}, plan }), null, 1));
