/* Part 1: rainfall futures and catastrophe bonds. */
import { frame, legend, fmt } from './chart.js';
import { priceCatBond, cdrFairValue, gridSf } from './pricing.js';

const S = { 1: 'var(--series-1)', 2: 'var(--series-2)', 3: 'var(--series-3)', 4: 'var(--series-4)' };
const el = (id) => document.getElementById(id);
const h = (s) => s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
const tile = (k, v, s, cls = '') => `<div class="tile"><div class="k">${k}</div><div class="v ${cls}">${v}</div>${s ? `<div class="s">${s}</div>` : ''}</div>`;

let W = null;

/* ---------------- contract spec cards ---------------- */
function contractCards() {
  el('contract-cards').innerHTML = Object.values(W.cities).map((c) => {
    const k = c.contract;
    const traded = k.status === 'traded';
    const months = k.months.join(' · ');
    return `<div>
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
        <strong class="mono">${h(k.code)}</strong>
        <span class="badge ${traded ? 'traded' : 'constructed'}">${traded ? 'traded · NCDEX' : 'constructed'}</span>
      </div>
      <dl class="kv">
        <dt>City</dt><dd>${h(c.label)}</dd>
        <dt>Season</dt><dd>${c.window[0]} → ${c.window[1]}</dd>
        <dt>Anchor</dt><dd>${fmt.mm(c.anchor_mm, 1)}</dd>
        <dt>Tick</dt><dd>${k.tick_mm} mm = ₹${k.multiplier_inr_per_mm}</dd>
        <dt>Months</dt><dd>${h(months)}</dd>
        <dt>Grid cell</dt><dd>${c.cell.lat}°N ${c.cell.lon}°E</dd>
        <dt>Grid normal</dt><dd>${fmt.mm(c.grid_season_normal_mm, 0)}</dd>
        <dt>Bias applied</dt><dd>×${fmt.num(c.bias.imd_grid.factor, 3)}</dd>
      </dl>
      <p class="hint" style="margin-top:10px">${h(c.season_basis)}</p>
    </div>`;
  }).join('');
}

/* ---------------- Mumbai: model versus actual ---------------- */
function mumbaiHeadline() {
  const c = W.rainmumbai_comparison;
  const mult = W.cities.mumbai.contract.multiplier_inr_per_mm;
  const o = c.official_components;
  el('mumbai-headline').innerHTML = `
    <div style="display:flex;flex-wrap:wrap;gap:30px;align-items:flex-start">
      <div style="flex:1 1 260px">
        <div class="k" style="font-size:.76rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:.06em;font-weight:600">Model error, RAINMUMBAI Sep 2026</div>
        <div class="hero-number ${c.model_error_mm < 0 ? 'neg' : 'pos'}" style="color:${c.model_error_mm < 0 ? 'var(--bad)' : 'var(--good)'}">
          ${fmt.signed(c.model_error_mm, 2)}<span class="unit">mm</span>
        </div>
        <div style="color:var(--text-secondary);font-size:.92rem;margin-top:6px">
          ${fmt.inr(Math.abs(c.model_error_inr_per_lot), 0)} per lot &mdash; the model quoted
          <span class="mono">${fmt.mm(c.model_fair_value_season_start_mm, 1)}</span> before the
          season and the contract settled at <span class="mono">${fmt.mm(c.official_settlement_mm, 2)}</span>.
        </div>
      </div>
      <div class="tiles" style="flex:2 1 460px">
        ${tile('Settlement value', fmt.mm(c.official_settlement_mm, 2), 'mean of Colaba &amp; Santacruz')}
        ${tile('Contract value', fmt.inr(c.contract_value_at_settlement_inr), `at ₹${mult}/mm`)}
        ${tile('Santacruz 2026', fmt.mm(o.santacruz_mm, 1), `${fmt.signed(o.santacruz_departure_pct, 0)}% vs normal`)}
        ${tile('Colaba 2026', fmt.mm(o.colaba_mm, 1), `${fmt.signed(o.colaba_departure_pct, 0)}% vs normal`)}
        ${tile('Climatology model', fmt.mm(c.model_fair_value_season_start_mm, 1), 'anchor, no tilt')}
        ${tile(`Forecast model (${h(c.forecast_variant)})`, fmt.mm(c.model_fair_value_with_forecast_mm, 1), `${fmt.signed(c.forecast_error_mm, 0)} mm error`)}
      </div>
    </div>
    <div class="callout warn" style="margin-top:20px">
      <strong>What is being compared.</strong> ${h(c.note)} The provisional gridded proxy for the
      2026 season gives ${fmt.mm(c.gridded_proxy_settlement_mm, 1)}, which is
      ${fmt.signed(c.gridded_proxy_error_mm, 0)} mm away from the official settlement &mdash; a
      measure of how far a reanalysis stand-in can sit from the stations a contract settles on.
    </div>`;
}

function monthlyChart() {
  // Only the September settlement is known from IMD's published station totals;
  // the three earlier months are marked against the provisional gridded proxy
  // and are drawn hollow to say so.
  const official = W.rainmumbai_comparison.official_settlement_mm;
  const rows = W.rainmumbai_comparison.monthly_exante.filter((r) => r.settled).map((r) => {
    const isSep = r.month === 9;
    const settled = isSep ? official : r.settlement_mm;
    return { ...r, settlement_mm: settled, official: isSep,
             error_mm: r.fair_value_mm - settled,
             pnl_long_inr_per_lot: (settled - r.fair_value_mm) * 50,
             proxy_mm: r.settlement_mm };
  });
  const vals = rows.flatMap((r) => [r.fair_value_mm, r.settlement_mm]);
  const lo = Math.min(...vals) - 120, hi = Math.max(...vals) + 120;
  const f = frame(el('chart-monthly'), {
    height: 290, xDomain: [-0.5, rows.length - 0.5], yDomain: [lo, hi], padLeft: 66,
    xTicks: rows.map((_, i) => i), xFormat: (i) => rows[i]?.contract.split('-')[1] ?? '',
    yFormat: (v) => fmt.int(v), yLabel: 'mm',
  });
  rows.forEach((r, i) => {
    const x = f.sx(i);
    f.el('line', { x1: x, x2: x, y1: f.sy(r.fair_value_mm), y2: f.sy(r.settlement_mm), stroke: 'var(--border-strong)', 'stroke-width': 2 });
    f.dot(i, r.fair_value_mm, { color: S[1] });
    f.dot(i, r.settlement_mm, { color: r.official ? S[2] : 'var(--surface-1)' });
    if (!r.official) f.el('circle', { cx: x, cy: f.sy(r.settlement_mm), r: 4.5, fill: 'none', stroke: S[2], 'stroke-width': 2 });
    const mid = (r.fair_value_mm + r.settlement_mm) / 2;
    f.el('text', { x: x + 11, y: f.sy(mid) + 4, class: 'series-label', fill: 'var(--text-secondary)' }).textContent = `${fmt.signed(r.error_mm, 0)} mm`;
  });
  f.hover(rows.flatMap((r, i) => [{ x: i, y: r.fair_value_mm, payload: r }]), (r) =>
    `<b>${r.contract}</b><br>model ${fmt.mm(r.fair_value_mm, 1)}<br>settled ${fmt.mm(r.settlement_mm, 1)}${r.official ? ' (IMD stations)' : ' (provisional proxy)'}<br>error ${fmt.signed(r.error_mm, 1)} mm<br>P&amp;L long ${fmt.inr(r.pnl_long_inr_per_lot)}`);
  legend(el('legend-monthly'), [
    { color: S[1], label: 'Model fair value, quoted 31 May 2026' },
    { color: S[2], label: 'Settlement from IMD station totals (September)' },
    { color: 'transparent', ring: S[2], label: 'Settlement from the provisional gridded proxy (June–August)' },
  ]);
  el('legend-monthly').insertAdjacentHTML('beforeend',
    `<span class="item" style="color:var(--text-muted)">Under climatology every contract month has the
     same fair value &mdash; the anchor &mdash; because the expected deviation is zero whatever the
     horizon.</span>`);
}

function pathChart(cityKey, host, legendHost) {
  const c = W.cities[cityKey];
  const path = c.current_season.path;
  const refs = c.reference_seasons;
  const series = [
    { key: 'wettest', color: S[3] }, { key: 'median', color: 'var(--text-muted)' }, { key: 'driest', color: S[2] },
  ];
  const all = [...path.map((p) => p.spot), ...series.flatMap((s) => refs[s.key].spot)];
  const f = frame(host, {
    height: 290, padLeft: 62,
    xDomain: [0, Math.max(c.current_season.days_in_season - 1, 1)],
    yDomain: [Math.min(...all) * 0.97, Math.max(...all) * 1.02],
    // Tick labels come from the season calendar, not the observed days, so the
    // axis stays dated past the point the current season has reached.
    xFormat: (i) => {
      const start = new Date(`${c.current_season.year}-${c.window[0]}T00:00:00`);
      const d = new Date(start.getTime() + Math.round(i) * 86400000);
      return d.toLocaleDateString('en-GB', { month: 'short', day: 'numeric' });
    },
    yFormat: fmt.int, yLabel: 'spot, mm',
  });
  f.hline(c.anchor_mm, { color: 'var(--border-strong)', label: `anchor ${fmt.mm(c.anchor_mm, 1)}` });
  for (const s of series) f.line(refs[s.key].spot.map((v, i) => [i, v]), { color: s.color, w: 1.5, opacity: 0.55, dash: '3 3' });
  f.line(path.map((p, i) => [i, p.spot]), { color: S[1], w: 2.5 });
  f.hover(path.map((p, i) => ({ x: i, y: p.spot, payload: { ...p, i } })), (p) =>
    `<b>${new Date(p.date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}</b><br>spot ${fmt.mm(p.spot, 1)}<br>rain ${fmt.mm(p.rain, 1)} · normal ${fmt.mm(p.lpa, 1)}<br>value ${fmt.inr(p.spot * 50)}`);
  legend(legendHost, [
    { color: S[1], line: true, label: `2026 season (${c.current_season.days_elapsed} of ${c.current_season.days_in_season} days)` },
    { color: S[3], line: true, label: `wettest season on record (${refs.wettest.year})` },
    { color: 'var(--text-muted)', line: true, label: `median season (${refs.median.year})` },
    { color: S[2], line: true, label: `driest season on record (${refs.driest.year})` },
  ]);
}

function backtestChart() {
  const bt = W.cities.mumbai.futures.backtest;
  const rows = bt.rows.filter((r) => r.complete);
  const vals = rows.flatMap((r) => [r.settlement_mm, r.fair_value_forecast_mm, r.fair_value_anchor_mm]);
  const f = frame(el('chart-backtest'), {
    height: 300, padLeft: 62,
    xDomain: [rows[0].year, rows.at(-1).year],
    yDomain: [Math.min(...vals) * 0.95, Math.max(...vals) * 1.03],
    xFormat: (v) => Math.round(v), yFormat: fmt.int, yLabel: 'mm',
  });
  f.line(rows.map((r) => [r.year, r.fair_value_anchor_mm]), { color: 'var(--text-muted)', w: 1.5, dash: '4 3' });
  f.line(rows.map((r) => [r.year, r.fair_value_forecast_mm]), { color: S[2], w: 2 });
  f.line(rows.map((r) => [r.year, r.settlement_mm]), { color: S[1], w: 2.5 });
  for (const r of rows) f.dot(r.year, r.settlement_mm, { color: S[1], r: 2.6, ring: false });
  f.hover(rows.map((r) => ({ x: r.year, y: r.settlement_mm, payload: r })), (r) =>
    `<b>${r.year}</b><br>settled ${fmt.mm(r.settlement_mm, 0)}<br>climatology ${fmt.mm(r.fair_value_anchor_mm, 0)} (${fmt.signed(r.error_anchor_mm, 0)})<br>${h(r.forecast_variant)} ${fmt.mm(r.fair_value_forecast_mm, 0)} (${fmt.signed(r.error_forecast_mm, 0)})`);
  legend(el('legend-backtest'), [
    { color: S[1], line: true, label: 'realised settlement' },
    { color: 'var(--text-muted)', line: true, label: 'climatology model (the anchor)' },
    { color: S[2], line: true, label: 'walk-forward statistical forecast' },
  ]);
  const a = bt.anchor_model, t = bt.forecast_model;
  el('backtest-tiles').innerHTML = [
    tile('Seasons tested', bt.n_years, '1991 → 2025'),
    tile('Climatology MAE', fmt.mm(a.mae_mm, 0), `bias ${fmt.signed(a.bias_mm, 0)} mm · RMSE ${fmt.int(a.rmse_mm)}`),
    tile('Forecast MAE', fmt.mm(t.mae_mm, 0), `bias ${fmt.signed(t.bias_mm, 0)} mm · RMSE ${fmt.int(t.rmse_mm)}`),
    tile('Forecast wins', `${fmt.num(bt.forecast_beats_anchor_pct, 0)}%`, `identical in ${fmt.num(bt.models_identical_pct, 0)}% of years`),
    tile('Mean absolute P&amp;L', fmt.inr(bt.mean_abs_pnl_inr_per_lot), 'per lot, climatology quote'),
  ].join('');
}

/* ---------------- does the seasonal forecast know anything? ---------------- */
function forecastCard() {
  const cities = Object.values(W.cities);
  const state = cities[0].forecast.state_now;
  const names = { climatology: 'climatology', trend: 'linear trend', enso: 'Niño 3.4',
                  enso_iod: 'Niño 3.4 + IOD', enso_trend: 'Niño 3.4 + trend' };

  el('forecast-state').innerHTML = [
    tile('Niño 3.4 today', `${fmt.signed(state.nino34, 2)} °C`,
      `${h(state.nino34_months)} mean · ${state.nino34 > 1 ? 'strong El Niño' : state.nino34 > 0.5 ? 'El Niño' : state.nino34 < -0.5 ? 'La Niña' : 'neutral'}`,
      state.nino34 > 0 ? 'pos' : 'neg'),
    tile('Dipole Mode Index', state.dmi === null ? 'not published' : fmt.signed(state.dmi, 2),
      state.dmi === null ? 'HadISST lags several months' : 'same window'),
    ...cities.map((c) => tile(`${h(c.label)} forecast`, names[c.forecast.selected] ?? c.forecast.selected,
      c.forecast.selected === 'climatology' ? 'nothing beat climatology'
        : `factor ${fmt.num(c.forecast.factor_now.factor, 3)}`)),
  ].join('');

  const variants = Object.keys(names);
  el('forecast-skill').innerHTML = `
    <thead><tr><th>Out-of-sample RMSE, as a ratio to the long-period average</th>
      ${cities.map((c) => `<th class="num">${h(c.label)}</th>`).join('')}</tr></thead>
    <tbody>${variants.map((v) => `<tr>
      <td>${h(names[v])}</td>
      ${cities.map((c) => {
        const s2 = c.forecast.skills[v];
        if (!s2 || !s2.usable) return '<td class="num">—</td>';
        const picked = c.forecast.selected === v;
        const better = s2.skill_vs_climatology > 0;
        return `<td class="num" style="${picked ? 'font-weight:650' : ''};color:${
          v === 'climatology' ? 'inherit' : better ? 'var(--good)' : 'var(--text-muted)'}">
          ${fmt.num(s2.rmse, 3)}${v === 'climatology' ? '' : ` <span class="hint">${fmt.signed(s2.skill_vs_climatology * 100, 1)}%</span>`}
          ${picked ? ' ✓' : ''}</td>`;
      }).join('')}</tr>`).join('')}</tbody>
    <caption>Each season is predicted by a model fitted only on seasons before it, and all variants
      are scored on the same ${cities[0].forecast.skills.climatology.n_scored} seasons. A variant is
      used only if it beats climatology; the tick marks the one selected. Read the margins
      sceptically: five candidates scored on ${cities[0].forecast.skills.climatology.n_scored} seasons,
      chosen on the same numbers they report.</caption>`;

  const rows = cities.map((c) => {
    const f = c.forecast;
    const fn = f.factor_now;
    return `<tr><td>${h(c.label)}</td>
      <td>${h(names[fn.variant] ?? fn.variant)}</td>
      <td class="num">${fmt.num(fn.factor, 3)}</td>
      <td class="num">${fmt.mm(fn.factor * c.anchor_mm, 0)}</td>
      <td>${h(fn.reason)}</td></tr>`;
  }).join('');
  el('forecast-now').innerHTML = `
    <thead><tr><th>City</th><th>Model in use</th><th class="num">Factor</th>
      <th class="num">Implied season total</th><th>Why</th></tr></thead><tbody>${rows}</tbody>`;
}

/* ---------------- live pricing for Chennai and Bengaluru ---------------- */
const liveState = { factor: null, lambda: 0 };

function liveControls() {
  el('live-controls').innerHTML = `
    <div class="ctl" style="flex:1 1 280px">
      <label for="f-factor">Seasonal forecast, % of the long-period average
        <span class="val" id="f-factor-v"></span></label>
      <input type="range" id="f-factor" min="70" max="130" step="1">
    </div>
    <div class="ctl" style="flex:1 1 240px">
      <label for="f-lambda">Market price of risk λ <span class="val" id="f-lambda-v"></span></label>
      <input type="range" id="f-lambda" min="-0.5" max="0.5" step="0.05" value="0">
    </div>
    <div class="ctl"><label>&nbsp;</label>
      <button class="segmented" style="padding:0"><button id="f-reset" aria-pressed="false">Reset to IMD outlook</button></button>
    </div>`;
  const fs = el('f-factor'), ls = el('f-lambda');
  fs.value = 100;
  const sync = () => {
    liveState.factor = +fs.value / 100;
    liveState.lambda = +ls.value;
    el('f-factor-v').textContent = `${fs.value}%`;
    el('f-lambda-v').textContent = (+ls.value).toFixed(2);
    renderLive();
  };
  fs.addEventListener('input', sync);
  ls.addEventListener('input', sync);
  el('f-reset').addEventListener('click', () => { fs.value = 100; ls.value = 0; sync(); });
  sync();
}

function renderLive() {
  const keys = ['chennai', 'bengaluru'];
  el('live-cards').innerHTML = keys.map((k) => `
    <div class="card" style="margin:0">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
        <h3 style="font-size:1.02rem">${h(W.cities[k].label)}</h3>
        <span class="badge constructed">${h(W.cities[k].contract.code)}</span>
      </div>
      <p class="hint" id="live-hint-${k}"></p>
      <div id="live-tiles-${k}" class="tiles"></div>
      <div id="live-sc-${k}" style="margin-top:14px"></div>
      <div id="live-path-${k}" style="margin-top:12px"></div>
      <div class="legend" id="live-legend-${k}"></div>
      <div id="live-report-${k}" class="sources" style="margin-top:12px"></div>
    </div>`).join('');

  for (const k of keys) {
    const c = W.cities[k];
    const v = c.futures.valuation_now;
    const mult = c.contract.multiplier_inr_per_mm;
    const fv = cdrFairValue({
      spot: v.spot_mm, remainingNormal: v.remaining_normal_mm, remainingSd: v.remaining_sd_mm,
      factor: liveState.factor, lambda: liveState.lambda, trend: 0,
    });
    const band = c.forecast_config.forecast_band;
    const low = cdrFairValue({ spot: v.spot_mm, remainingNormal: v.remaining_normal_mm, remainingSd: v.remaining_sd_mm, factor: band[0], lambda: liveState.lambda }).fair;
    const high = cdrFairValue({ spot: v.spot_mm, remainingNormal: v.remaining_normal_mm, remainingSd: v.remaining_sd_mm, factor: band[1], lambda: liveState.lambda }).fair;
    const dep = (fv.fair - c.anchor_mm) / c.anchor_mm;

    el(`live-hint-${k}`).innerHTML = `Season ${c.window[0]} → ${c.window[1]} ·
      ${c.current_season.days_elapsed} of ${c.current_season.days_in_season} days observed ·
      final settlement ${new Date(v.expiry).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}`;
    el(`live-tiles-${k}`).innerHTML = [
      tile('Fair value now', fmt.mm(fv.fair, 1), `${fmt.inr(fv.fair * mult)} per lot`),
      tile('Spot today', fmt.mm(v.spot_mm, 1), `anchor ${fmt.mm(c.anchor_mm, 1)}`),
      tile('Vs normal', `${fmt.signed(dep * 100, 1)}%`, dep < 0 ? 'dry season so far' : 'wet season so far', dep < 0 ? 'neg' : 'pos'),
      tile('Still to come', fmt.mm(v.remaining_normal_mm, 0), `σ ${fmt.mm(v.remaining_sd_mm, 0)}`),
    ].join('');

    const rows = [
      { label: `IMD band low (${fmt.pct(band[0], 0)})`, v: low },
      { label: 'your forecast', v: fv.fair },
      { label: `IMD band high (${fmt.pct(band[1], 0)})`, v: high },
    ];
    el(`live-sc-${k}`).innerHTML = `<table><thead><tr><th>Scenario</th><th class="num">Fair value</th><th class="num">Per lot</th><th class="num">vs spot</th></tr></thead><tbody>${
      rows.map((r) => `<tr><td>${r.label}</td><td class="num">${fmt.mm(r.v, 1)}</td><td class="num">${fmt.inr(r.v * mult)}</td><td class="num">${fmt.signed(r.v - v.spot_mm, 1)} mm</td></tr>`).join('')
    }</tbody></table>`;

    pathChart(k, el(`live-path-${k}`), el(`live-legend-${k}`));

    const f = c.forecast_config;
    const bits = [];
    for (const [key, val] of Object.entries(f)) {
      if (typeof val !== 'object' || val === null) continue;
      const note = val.note || val.spatial_note || val.tamil_nadu || '';
      const src = val.source || '';
      const nums = Object.entries(val).filter(([kk, vv]) => typeof vv === 'number')
        .map(([kk, vv]) => `${kk.replace(/_/g, ' ')} ${fmt.num(vv, 1)}`).join(' · ');
      bits.push(`<li><strong>${key.replace(/_/g, ' ')}</strong> — ${h(nums)}${note ? `. ${h(note)}` : ''}${src ? `<br><span class="hint">${h(src)}</span>` : ''}</li>`);
    }
    el(`live-report-${k}`).innerHTML = `<details><summary style="cursor:pointer;color:var(--text-secondary)">Weather reports behind this price</summary><ul>${bits.join('')}</ul></details>`;
  }
}

/* ---------------- catastrophe bond pricer ---------------- */
const bondState = { city: 'mumbai', bond: 'flood', attachQ: 0.90, exhaustQ: 0.99, tenor: 1, rule: 'wang', param: 0.25, method: 'mc' };

function bondControls() {
  el('bond-controls').innerHTML = `
    <div class="ctl"><label for="b-city">City</label>
      <select id="b-city">${Object.values(W.cities).map((c) => `<option value="${c.key}">${h(c.label)}</option>`).join('')}</select></div>
    <div class="ctl"><label for="b-bond">Bond</label>
      <select id="b-bond">
        <option value="flood">flood · MAX3 trigger</option>
        <option value="drought">drought · seasonal total</option>
      </select></div>
    <div class="ctl" style="flex:1 1 180px"><label for="b-attach">Attachment <span class="val" id="b-attach-v"></span></label>
      <input type="range" id="b-attach" min="50" max="98" step="1" value="90"></div>
    <div class="ctl" style="flex:1 1 180px"><label for="b-exhaust">Exhaustion <span class="val" id="b-exhaust-v"></span></label>
      <input type="range" id="b-exhaust" min="80" max="99.8" step="0.2" value="99"></div>
    <div class="ctl"><label for="b-tenor">Tenor</label>
      <select id="b-tenor"><option value="1">1 year</option><option value="3">3 years</option></select></div>
    <div class="ctl"><label for="b-rule">Risk premium rule</label>
      <select id="b-rule">
        <option value="wang">R2 Wang transform</option>
        <option value="r1">R1 expected-loss multiple</option>
        <option value="sd">R3 SD loading</option>
      </select></div>
    <div class="ctl" style="flex:1 1 170px"><label for="b-param"><span id="b-param-label">λ</span> <span class="val" id="b-param-v"></span></label>
      <input type="range" id="b-param" min="0" max="1" step="0.05" value="0.25"></div>
    <div class="ctl"><label>Method</label>
      <div class="segmented" id="b-method">
        <button data-m="mc" aria-pressed="true">fitted MC</button>
        <button data-m="burn" aria-pressed="false">burn</button>
      </div></div>`;

  const bind = (id, fn) => el(id).addEventListener('input', fn);
  const sync = () => {
    bondState.city = el('b-city').value;
    bondState.bond = el('b-bond').value;
    bondState.tenor = +el('b-tenor').value;
    bondState.rule = el('b-rule').value;
    const inv = bondState.bond === 'drought';
    const aq = +el('b-attach').value / 100, eq = +el('b-exhaust').value / 100;
    bondState.attachQ = inv ? 1 - aq : aq;
    bondState.exhaustQ = inv ? 1 - eq : eq;
    bondState.param = +el('b-param').value;
    el('b-param-label').textContent = bondState.rule === 'wang' ? 'λ' : bondState.rule === 'r1' ? 'multiple m' : 'β';
    const p = el('b-param');
    if (bondState.rule === 'r1') { p.min = 1; p.max = 4; p.step = 0.1; } else { p.min = 0; p.max = 1; p.step = 0.05; }
    el('b-param-v').textContent = fmt.num(bondState.param, 2);
    el('b-attach-v').textContent = `${inv ? 'driest ' : ''}${fmt.num(aq * 100, 0)}th pct`;
    el('b-exhaust-v').textContent = `${inv ? 'driest ' : ''}${fmt.num(eq * 100, 1)}th pct`;
    renderBond();
  };
  ['b-city', 'b-bond', 'b-attach', 'b-exhaust', 'b-tenor', 'b-rule', 'b-param'].forEach((id) => bind(id, sync));
  el('b-method').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
    bondState.method = b.dataset.m;
    el('b-method').querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    renderBond();
  }));
  sync();
}

function renderBond() {
  const c = W.cities[bondState.city];
  const spec = c.bonds[bondState.bond];
  const trigger = spec.trigger;
  const grid = c.quantile_grids[trigger];
  const sample = c.fits[trigger].sample_values;
  const inv = !!spec.inverted;
  const attach = gridPpfLocal(grid, bondState.attachQ);
  const exhaust = gridPpfLocal(grid, bondState.exhaustQ);
  const ok = inv ? attach > exhaust : exhaust > attach;
  const res = ok ? priceCatBond({
    attach, exhaust, tenor: bondState.tenor, inverted: inv, grid, sample,
    rule: bondState.rule, m: bondState.param, lam: bondState.param, beta: bondState.param,
    rate: W.meta.discount.rate, collateral: W.meta.discount.rate,
    nPaths: bondState.method === 'burn' && bondState.tenor === 1 ? sample.length : 20000,
    method: bondState.method,
  }) : null;

  if (!res) {
    el('bond-tiles').innerHTML = tile('Invalid', '—', 'exhaustion must sit beyond attachment');
    return;
  }
  el('bond-tiles').innerHTML = [
    tile('Fair spread', fmt.pct(res.fairSpread, 2), `over the ${fmt.pct(W.meta.discount.rate, 2)} collateral yield`),
    tile('Expected loss', fmt.pct(res.elAnnual, 2), 'per year, of face'),
    tile('Multiple', fmt.num(res.fairSpread / Math.max(res.elAnnual, 1e-9), 2) + '×', 'spread ÷ expected loss'),
    tile('P(attachment)', fmt.pct(res.probAttach, 1), `1 in ${fmt.num(1 / Math.max(res.probAttach, 1e-9), 1)} seasons`),
    tile('P(total loss)', fmt.pct(res.probExhaust, 2), 'index past exhaustion'),
    tile('99% CVaR', fmt.num(res.cvar99, 1), 'loss per 100 of face'),
  ].join('');

  // exceedance, with the band the 45-season record supports behind it
  const unc = spec.uncertainty && spec.uncertainty.n_boot ? spec.uncertainty : null;
  // Compare the quantiles the sliders set, not the interpolated levels: the
  // browser reads them off a 251-point grid and Python off the fitted function,
  // so the millimetre values differ in the last decimals.
  const atDefaults = Math.abs(bondState.attachQ - spec.spec.quantile_attach) < 1e-9
    && Math.abs(bondState.exhaustQ - spec.spec.quantile_exhaust) < 1e-9
    && bondState.tenor === spec.spec.tenors[0];
  const bandRows = unc && atDefaults ? unc.exceedance_band : null;
  const topProb = Math.max(res.exceedance[1].prob, bandRows ? bandRows[1].hi : 0) * 1.25;
  const f = frame(el('chart-exceedance'), {
    height: 250, padLeft: 54, xDomain: [0, 100], yDomain: [0, Math.max(0.02, Math.min(1, topProb))],
    xFormat: (v) => fmt.int(v), yFormat: (v) => fmt.pct(v, 1), yLabel: 'probability', xLabel: 'loss per 100 face',
  });
  if (bandRows) f.band(bandRows.map((r) => [r.loss, r.hi, r.lo]), { color: S[1], opacity: 0.16 });
  f.line(res.exceedance.map((p) => [p.loss, p.prob]), { color: S[1], w: 2.5 });
  f.vline(res.var99, { color: S[2], label: `99% VaR ${fmt.num(res.var99, 0)}` });
  f.hover(res.exceedance.map((p, i) => ({ x: p.loss, y: p.prob, payload: { ...p, b: bandRows ? bandRows[i] : null } })), (p) =>
    `loss &gt; ${fmt.num(p.loss, 0)}<br>${fmt.pct(p.prob, 2)}` +
    (p.b ? `<br><span style="opacity:.7">band ${fmt.pct(p.b.lo, 2)} – ${fmt.pct(p.b.hi, 2)}</span>` : ''));
  legend(el('legend-exceedance'), [
    { color: S[1], line: true, label: `${bondState.method === 'burn' ? 'burn analysis on observed seasons' : 'fitted distribution, Monte Carlo'} (${fmt.int(res.nPaths)} paths)` },
    { color: S[2], line: true, label: '99% value at risk' },
    ...(bandRows ? [{ color: S[1], label: `5th–95th percentile over ${fmt.int(unc.n_boot)} resamples of the ${unc.n_seasons} observed seasons` }] : []),
  ]);
  el('bond-uncertainty').innerHTML = !unc ? '' : (atDefaults
    ? `<div class="callout"><strong>How much of this is actually known?</strong> Resampling the
       ${unc.n_seasons} observed seasons, refitting and re-pricing ${fmt.int(unc.n_boot)} times puts
       expected loss anywhere between <strong>${fmt.pct(unc.expected_loss_annual.p05, 2)}</strong> and
       <strong>${fmt.pct(unc.expected_loss_annual.p95, 2)}</strong> (point estimate
       ${fmt.pct(unc.point_estimate.expected_loss_annual, 2)}), and the fair spread between
       ${fmt.pct(unc.fair_spread.p05, 2)} and ${fmt.pct(unc.fair_spread.p95, 2)}. The exhaustion point
       sits near a 1-in-100 event estimated from ${unc.n_seasons} years.</div>`
    : `<p class="hint">The uncertainty band is computed for the configured attachment
       (${fmt.mm(spec.attach_mm, 0)}) and exhaustion (${fmt.mm(spec.exhaust_mm, 0)}) at the
       ${spec.spec.tenors[0]}-year tenor; reset the sliders to see it.</p>`);

  // trigger placement
  const xs = grid.x, qs = grid.q;
  const lo = Math.min(xs[0], Math.min(...sample)), hi = Math.max(xs.at(-1), Math.max(...sample));
  const g2 = frame(el('chart-trigger'), {
    height: 250, padLeft: 54, xDomain: [lo, hi], yDomain: [0, 1],
    xFormat: (v) => fmt.int(v), yFormat: (v) => fmt.pct(v, 0),
    yLabel: 'P(index ≤ x)', xLabel: `${trigger}, mm`,
  });
  g2.line(xs.map((x, i) => [x, qs[i]]), { color: S[1], w: 2.5 });
  const sorted = sample.slice().sort((a, b) => a - b);
  sorted.forEach((v, i) => g2.dot(v, (i + 0.5) / sorted.length, { color: 'var(--text-muted)', r: 2.6, ring: false }));
  g2.vline(attach, { color: S[2], label: `attach ${fmt.int(attach)}` });
  g2.vline(exhaust, { color: S[4], dy: 32, label: `exhaust ${fmt.int(exhaust)}` });
  const pot = (c.pot && c.pot[trigger] || []).find((x) => Math.abs(x.threshold_quantile - 0.95) < 1e-9);
  if (pot && pot.return_levels['0.99']) {
    g2.vline(pot.return_levels['0.99'], { color: S[3], dash: '2 3', dy: 16,
      label: `POT 1-in-100 ${fmt.int(pot.return_levels['0.99'])}` });
  }
  legend(el('legend-trigger'), [
    { color: S[1], line: true, label: `fitted ${h(c.fits[trigger].best.family)} (AIC ${fmt.num(c.fits[trigger].best.aic, 1)}, KS p ${fmt.num(c.fits[trigger].best.ks_pvalue, 2)})` },
    ...(pot ? [{ color: S[3], line: true, label: `peaks-over-threshold 1-in-100 (ξ = ${fmt.num(pot.shape_xi, 2)}, ${pot.n_peaks} peaks) — an independent read on the same tail` }] : []),
    { color: 'var(--text-muted)', label: `${sorted.length} observed seasons` },
    { color: S[2], line: true, label: 'attachment' }, { color: S[4], line: true, label: 'exhaustion' },
  ]);

  // reference table: python results at the config defaults
  const ref = spec.results.filter((r) => r.bond.tenor === bondState.tenor
    && r.rule.rule === (bondState.rule === 'wang' ? 'wang' : bondState.rule));
  const rows = ref.map((r) => ({
    method: r.method, param: r.rule.rule === 'wang' ? r.rule.lam : r.rule.rule === 'r1' ? r.rule.m : r.rule.beta,
    spread: r.fair_spread, el: r.expected_loss_annual, pa: r.prob_attach, pe: r.prob_exhaust,
    var99: r.var99, se: r.standard_error,
  })).sort((a, b) => a.param - b.param || a.method.localeCompare(b.method));
  el('bond-reference-note').innerHTML = `Python reference run for ${h(c.label)} ·
    ${h(bondState.bond)} · ${bondState.tenor}-year · attachment ${fmt.mm(spec.attach_mm, 0)} /
    exhaustion ${fmt.mm(spec.exhaust_mm, 0)} (the config defaults, which the sliders above start
    from). Burn, Monte Carlo and quadrature should agree within sampling error.`;
  el('bond-reference').innerHTML = `
    <thead><tr><th>Method</th><th class="num">Rule parameter</th><th class="num">Expected loss</th>
      <th class="num">Fair spread</th><th class="num">P(attach)</th><th class="num">P(exhaust)</th>
      <th class="num">99% VaR</th><th class="num">MC std. error</th></tr></thead>
    <tbody>${rows.map((r) => `<tr><td>${r.method}</td><td class="num">${fmt.num(r.param, 2)}</td>
      <td class="num">${fmt.pct(r.el, 2)}</td><td class="num">${fmt.pct(r.spread, 2)}</td>
      <td class="num">${fmt.pct(r.pa, 1)}</td><td class="num">${fmt.pct(r.pe, 2)}</td>
      <td class="num">${fmt.num(r.var99, 1)}</td><td class="num">${r.se === null ? '—' : fmt.pct(r.se, 3)}</td></tr>`).join('')}</tbody>`;
}

function gridPpfLocal(grid, u) {
  const { q, x } = grid;
  if (u <= q[0]) return x[0];
  if (u >= q.at(-1)) return x.at(-1);
  let lo = 0, hi = q.length - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (q[mid] <= u) lo = mid; else hi = mid; }
  const w = (u - q[lo]) / (q[hi] - q[lo]);
  return x[lo] + w * (x[hi] - x[lo]);
}

function premiumTable() {
  const c = W.cities.mumbai;
  const spec = c.bonds.flood;
  const rows = spec.results.filter((r) => r.method === 'mc' && r.bond.tenor === 1);
  el('premium-table').innerHTML = `
    <caption>Mumbai flood bond, 1-year, attachment ${fmt.mm(spec.attach_mm, 0)} /
      exhaustion ${fmt.mm(spec.exhaust_mm, 0)} on the 3-day maximum. Expected loss is the same in
      every row &mdash; only the compensation demanded for it changes.</caption>
    <thead><tr><th>Rule</th><th class="num">Parameter</th><th class="num">Fair spread</th>
      <th class="num">Multiple of expected loss</th><th class="num">Coupon at par</th></tr></thead>
    <tbody>${rows.map((r) => `<tr><td>${h(r.rule.label.split(' ').slice(0, 3).join(' '))}</td>
      <td class="num">${fmt.num(r.rule.rule === 'wang' ? r.rule.lam : r.rule.rule === 'r1' ? r.rule.m : r.rule.beta, 2)}</td>
      <td class="num">${fmt.pct(r.fair_spread, 2)}</td>
      <td class="num">${fmt.num(r.fair_spread / Math.max(r.expected_loss_annual, 1e-9), 2)}×</td>
      <td class="num">${fmt.pct(W.meta.discount.rate + r.fair_spread, 2)}</td></tr>`).join('')}</tbody>
    <tfoot><tr><td>Expected loss</td><td></td><td class="num">${fmt.pct(rows[0].expected_loss_annual, 2)}</td>
      <td class="num">1.00×</td><td class="num">${fmt.pct(W.meta.discount.rate + rows[0].expected_loss_annual, 2)}</td></tr></tfoot>`;
}

export function renderWeather(data) {
  W = data;
  contractCards();
  forecastCard();
  mumbaiHeadline();
  monthlyChart();
  pathChart('mumbai', el('chart-path-mumbai'), el('legend-path-mumbai'));
  backtestChart();
  liveControls();
  bondControls();
  premiumTable();
  return W;
}

export function heroWeatherTiles(data) {
  const c = data.rainmumbai_comparison;
  const ch = data.cities.chennai.futures.valuation_now;
  const bl = data.cities.bengaluru.futures.valuation_now;
  return [
    tile('RAINMUMBAI Sep 2026', fmt.mm(c.official_settlement_mm, 1),
      `settled · model missed by ${fmt.signed(c.model_error_mm, 1)} mm`),
    tile('Model error per lot', fmt.inr(Math.abs(c.model_error_inr_per_lot)),
      `${c.model_error_mm < 0 ? 'quoted under' : 'quoted over'} the settlement`),
    tile('RAINCHENNAI-C fair value', fmt.mm(ch.fair_value_mm, 1), 'constructed · season live today'),
    tile('RAINBLR-C fair value', fmt.mm(bl.fair_value_mm, 1), 'constructed · drought year'),
  ].join('');
}
