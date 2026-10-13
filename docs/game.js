/* Part 2: the Israeli (game) option. */
import { frame, legend, fmt } from './chart.js';
import { gameBundle, crrGame } from './pricing.js';

const S = { 1: 'var(--series-1)', 2: 'var(--series-2)', 3: 'var(--series-3)', 4: 'var(--series-4)' };
const el = (id) => document.getElementById(id);
const h = (s) => String(s).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
const tile = (k, v, s, cls = '') => `<div class="tile"><div class="k">${k}</div><div class="v ${cls}">${v}</div>${s ? `<div class="s">${s}</div>` : ''}</div>`;

let G = null;
const st = { strikePct: 1.05, tenor: 1, penaltyPct: 2, sigma: null, r: null, steps: 600, kind: 'put' };

function inputsCard() {
  const i = G.inputs;
  el('game-inputs').innerHTML = [
    tile('NIFTY 50 spot', fmt.num(i.s0, 2), `close, ${i.asof}`),
    tile('Volatility σ', fmt.pct(i.sigma, 2), 'India VIX, implied'),
    tile('Risk-free r', fmt.pct(i.r, 2), 'RBI repo + 10 bp'),
    tile('Dividend yield q', fmt.pct(i.q, 2), 'NSE Indices'),
    tile('Realised vol', i.realised_vol_1y === null ? 'not computed' : fmt.pct(i.realised_vol_1y, 2),
      i.realised_vol_1y === null ? 'history download blocked' : '1-year window'),
  ].join('');
  el('game-input-notes').innerHTML = '<ul>' + Object.values(i.sources).map((s) => `<li>${h(s)}</li>`).join('') + '</ul>';
}

function controls() {
  st.sigma = G.inputs.sigma; st.r = G.inputs.r;
  el('game-controls').innerHTML = `
    <div class="ctl"><label>Option</label>
      <div class="segmented" id="g-kind">
        <button data-k="put" aria-pressed="true">put</button>
        <button data-k="call" aria-pressed="false">call</button>
      </div></div>
    <div class="ctl" style="flex:1 1 190px"><label for="g-strike">Strike, % of spot <span class="val" id="g-strike-v"></span></label>
      <input type="range" id="g-strike" min="80" max="120" step="1" value="105"></div>
    <div class="ctl" style="flex:1 1 190px"><label for="g-pen">Cancellation penalty δ, % of spot <span class="val" id="g-pen-v"></span></label>
      <input type="range" id="g-pen" min="0" max="10" step="0.1" value="2"></div>
    <div class="ctl"><label for="g-tenor">Tenor</label>
      <select id="g-tenor">
        <option value="0.25">3 months</option><option value="0.5">6 months</option>
        <option value="1" selected>1 year</option><option value="2">2 years</option>
      </select></div>
    <div class="ctl" style="flex:1 1 170px"><label for="g-vol">Volatility σ <span class="val" id="g-vol-v"></span></label>
      <input type="range" id="g-vol" min="6" max="40" step="0.5" value="${(G.inputs.sigma * 100).toFixed(1)}"></div>
    <div class="ctl" style="flex:1 1 150px"><label for="g-rate">Rate r <span class="val" id="g-rate-v"></span></label>
      <input type="range" id="g-rate" min="3" max="9" step="0.1" value="${(G.inputs.r * 100).toFixed(1)}"></div>
    <div class="ctl"><label for="g-steps">Tree steps</label>
      <select id="g-steps"><option>200</option><option selected>600</option><option>1200</option><option>2000</option></select></div>`;
  const ids = ['g-strike', 'g-pen', 'g-tenor', 'g-vol', 'g-rate', 'g-steps'];
  const sync = () => {
    st.strikePct = +el('g-strike').value / 100;
    st.penaltyPct = +el('g-pen').value;
    st.tenor = +el('g-tenor').value;
    st.sigma = +el('g-vol').value / 100;
    st.r = +el('g-rate').value / 100;
    st.steps = +el('g-steps').value;
    el('g-strike-v').textContent = `${el('g-strike').value}% (${fmt.num(st.strikePct * G.inputs.s0, 0)})`;
    el('g-pen-v').textContent = `${st.penaltyPct}% (${fmt.num(st.penaltyPct / 100 * G.inputs.s0, 0)} pts)`;
    el('g-vol-v').textContent = fmt.pct(st.sigma, 1);
    el('g-rate-v').textContent = fmt.pct(st.r, 1);
    render();
  };
  ids.forEach((id) => el(id).addEventListener('input', sync));
  el('g-kind').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
    st.kind = b.dataset.k;
    el('g-kind').querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    render();
  }));
  sync();
}

function render() {
  const i = G.inputs;
  const args = {
    s0: i.s0, strike: st.strikePct * i.s0, r: st.r, q: i.q, sigma: st.sigma,
    maturity: st.tenor, steps: st.steps, kind: st.kind, penalty: (st.penaltyPct / 100) * i.s0,
  };
  const t0 = performance.now();
  const res = gameBundle(args);
  const ms = performance.now() - t0;
  const share = res.american > 0 ? res.cancellationValue / res.american : 0;

  el('game-tiles').innerHTML = [
    tile('Game value', fmt.num(res.price, 2), `index points · ${fmt.pct(res.price / i.s0, 2)} of spot`),
    tile('American value', fmt.num(res.american, 2), 'without the cancellation right'),
    tile('Cancellation right', fmt.num(res.cancellationValue, 2), `${fmt.pct(share, 1)} of the American value`),
    tile('European value', fmt.num(res.european, 2), 'no early exercise either'),
    tile('Intrinsic', fmt.num(res.intrinsic, 2), 'exercise now'),
    tile('Cap: intrinsic + δ', fmt.num(res.intrinsic + args.penalty, 2),
      res.price >= res.intrinsic + args.penalty - 1e-6 ? 'binding — issuer cancels at once' : 'not binding'),
  ].join('');

  const g = res.greeks;
  el('game-greeks').innerHTML = `
    <tbody>
      <tr><td>Delta &nbsp;<span class="hint">∂V/∂S</span></td><td class="num">${fmt.num(g.delta, 4)}</td></tr>
      <tr><td>Gamma &nbsp;<span class="hint">∂²V/∂S²</span></td><td class="num">${fmt.num(g.gamma, 6)}</td></tr>
      <tr><td>Vega &nbsp;<span class="hint">per 1% of σ</span></td><td class="num">${fmt.num(g.vega, 3)}</td></tr>
      <tr><td>Rho &nbsp;<span class="hint">per 1% of r</span></td><td class="num">${fmt.num(g.rho, 3)}</td></tr>
      <tr><td>Theta &nbsp;<span class="hint">per day</span></td><td class="num">${fmt.num(g.theta, 3)}</td></tr>
    </tbody>
    <caption>Tree with ${fmt.int(st.steps)} steps, priced in ${fmt.num(ms, 0)} ms in this browser.
      Greeks use a coarser tree for the bumps. Zero vega and theta are not a bug: where the penalty
      cap binds, the price is exactly intrinsic + δ and stops depending on anything else.</caption>`;

  el('game-checks').innerHTML = Object.entries(res.checks).map(([k, v]) =>
    `<span class="badge ${v ? 'traded' : 'hypo'}" style="margin-right:8px">${v ? '✓' : '✗'} ${h(k)}</span>`).join('')
    + `<span class="hint" style="margin-left:6px">bounds checked live on every re-price</span>`;

  boundaryChart(res, args);
}

function boundaryChart(res, args) {
  const pts = res.exerciseBoundary.filter((b) => b.boundary !== null);
  const host = el('chart-boundary');
  if (!pts.length) {
    host.innerHTML = `<p class="loading">No exercise region on this contract: with the penalty cap
      binding from the start the holder never exercises before the issuer cancels.</p>`;
    el('legend-boundary').innerHTML = '';
    return;
  }
  const ys = pts.map((p) => p.boundary).concat([args.strike, args.s0]);
  const f = frame(host, {
    height: 280, padLeft: 64, xDomain: [0, args.maturity],
    yDomain: [Math.min(...ys) * 0.97, Math.max(...ys) * 1.03],
    xFormat: (v) => `${fmt.num(v, 2)}y`, yFormat: fmt.int, yLabel: 'index level',
    xLabel: 'time from today',
  });
  f.hline(args.strike, { color: S[2], label: `strike ${fmt.int(args.strike)} — issuer's cancellation locus` });
  f.hline(args.s0, { color: 'var(--text-muted)', dash: '2 4', label: `spot ${fmt.int(args.s0)}` });
  f.line(pts.map((p) => [p.t, p.boundary]), { color: S[1], w: 2.5 });
  f.hover(pts.map((p) => ({ x: p.t, y: p.boundary, payload: p })), (p) =>
    `t = ${fmt.num(p.t, 3)}y<br>holder exercises at or below<br><b>${fmt.int(p.boundary)}</b>`);
  legend(el('legend-boundary'), [
    { color: S[1], line: true, label: st.kind === 'put' ? 'holder exercises below this level' : 'holder exercises above this level' },
    { color: S[2], line: true, label: 'the issuer\'s cancellation region collapses onto the strike' },
  ]);
}

function penaltyChart() {
  const atm = G.penalty_curve, itm = G.penalty_curve_itm || [];
  const f = frame(el('chart-penalty'), {
    height: 280, padLeft: 60, xDomain: [0, 8],
    yDomain: [0, Math.max(...itm.map((p) => p.price), ...atm.map((p) => p.price)) * 1.08],
    xFormat: (v) => `${fmt.num(v, 0)}%`, yFormat: fmt.int, yLabel: 'index points',
    xLabel: 'penalty δ, % of spot',
  });
  f.hline(G.american_reference, { color: S[1], dash: '3 4', label: `American value, 5% in the money: ${fmt.int(G.american_reference)}` });
  f.hline(G.atm_finding.american, { color: S[3], dash: '3 4', label: `American value, at the money: ${fmt.int(G.atm_finding.american)}` });
  f.line(itm.map((p) => [p.penalty_pct * 100, p.price]), { color: S[1], w: 2.5 });
  f.line(atm.map((p) => [p.penalty_pct * 100, p.price]), { color: S[3], w: 2.5 });
  const thr = G.atm_finding.threshold_pct * 100;
  f.vline(thr, { color: S[2], label: `δ* = ${fmt.num(thr, 2)}% (at the money)` });
  f.hover(itm.map((p) => ({ x: p.penalty_pct * 100, y: p.price, payload: p })), (p) => {
    const a = atm.find((x) => Math.abs(x.penalty_pct - p.penalty_pct) < 1e-9);
    return `δ = ${fmt.num(p.penalty_pct * 100, 2)}%<br>5% in-the-money ${fmt.num(p.price, 1)}<br>at the money ${a ? fmt.num(a.price, 1) : '—'}`;
  });
  legend(el('legend-penalty'), [
    { color: S[1], line: true, label: 'put struck 5% in the money (the reference contract)' },
    { color: S[3], line: true, label: 'put struck at the money' },
    { color: S[2], line: true, label: 'penalty above which the at-the-money cancellation right is worthless' },
  ]);
  el('penalty-hint').innerHTML = `With the strike at spot the holder's payoff is zero and the issuer's
    time value is not, so the issuer cancels immediately and the price is <em>exactly</em> the
    penalty &mdash; a straight line &mdash; until δ reaches
    <strong>${fmt.num(G.atm_finding.threshold_pct * 100, 2)}% of spot</strong>, where cancelling stops
    being worth it and the price becomes the American value of
    ${fmt.num(G.atm_finding.american, 1)} points.`;
}

function volChart() {
  const rows = G.vol_grid;
  const f = frame(el('chart-vol'), {
    height: 280, padLeft: 60,
    xDomain: [rows[0].sigma * 100, rows.at(-1).sigma * 100],
    yDomain: [0, Math.max(...rows.map((r) => r.american)) * 1.06],
    xFormat: (v) => `${fmt.num(v, 0)}%`, yFormat: fmt.int, yLabel: 'index points',
    xLabel: 'volatility σ',
  });
  f.line(rows.map((r) => [r.sigma * 100, r.american]), { color: 'var(--text-muted)', w: 2, dash: '5 3' });
  f.line(rows.map((r) => [r.sigma * 100, r.p5]), { color: S[1], w: 2.5 });
  f.line(rows.map((r) => [r.sigma * 100, r.p2]), { color: S[2], w: 2.5 });
  f.line(rows.map((r) => [r.sigma * 100, r.p1]), { color: S[3], w: 2.5 });
  f.vline(G.inputs.sigma * 100, { color: 'var(--border-strong)', label: 'India VIX today' });
  f.hover(rows.map((r) => ({ x: r.sigma * 100, y: r.american, payload: r })), (r) =>
    `σ = ${fmt.pct(r.sigma, 1)}<br>American ${fmt.num(r.american, 1)}<br>δ=5% ${fmt.num(r.p5, 1)}<br>δ=2% ${fmt.num(r.p2, 1)}<br>δ=1% ${fmt.num(r.p1, 1)}`);
  legend(el('legend-vol'), [
    { color: 'var(--text-muted)', line: true, label: 'American value (no cancellation right)' },
    { color: S[1], line: true, label: 'game value, δ = 5%' },
    { color: S[2], line: true, label: 'game value, δ = 2%' },
    { color: S[3], line: true, label: 'game value, δ = 1%' },
  ]);
}

function convergenceChart() {
  const rows = G.convergence;
  const vals = rows.map((r) => r.price);
  const f = frame(el('chart-convergence'), {
    height: 250, padLeft: 64,
    xDomain: [Math.log10(rows[0].steps), Math.log10(rows.at(-1).steps)],
    yDomain: [Math.min(...vals) * 0.998, Math.max(...vals) * 1.002],
    xTicks: rows.map((r) => Math.log10(r.steps)),
    xFormat: (v) => fmt.int(Math.pow(10, v)), yFormat: (v) => fmt.num(v, 1),
    yLabel: 'index points', xLabel: 'tree steps',
  });
  f.line(rows.map((r) => [Math.log10(r.steps), r.price]), { color: S[1], w: 2.5 });
  for (const r of rows) f.dot(Math.log10(r.steps), r.price, { color: S[1] });
  f.hover(rows.map((r) => ({ x: Math.log10(r.steps), y: r.price, payload: r })), (r) =>
    `${fmt.int(r.steps)} steps<br><b>${fmt.num(r.price, 3)}</b>`);
  legend(el('legend-convergence'), [{ color: S[1], line: true, label: `reference contract: ${fmt.pct(G.reference.strike_pct, 0)} strike, ${G.reference.tenor}y, δ = ${fmt.pct(G.reference.penalty_pct, 0)}` }]);
}

function methodTable() {
  el('method-table').innerHTML = `
    <thead><tr><th>Contract</th><th class="num">Tree, ${fmt.int(G.methods[0].steps)} steps</th>
      <th class="num">Monte Carlo</th><th class="num">MC vs tree</th>
      <th class="num">Finite difference</th><th class="num">FD vs averaged tree</th>
      <th class="num">Rigorous bracket</th></tr></thead>
    <tbody>${G.methods.map((m) => `<tr>
      <td>${fmt.pct(m.strike_pct, 0)} strike · δ ${fmt.pct(m.penalty_pct, 0)}</td>
      <td class="num">${fmt.num(m.tree_matched_steps, 2)}</td>
      <td class="num">${fmt.num(m.lsm, 2)} <span class="hint">± ${fmt.num(1.96 * m.lsm_se, 2)}</span></td>
      <td class="num" style="color:${Math.abs(m.lsm_vs_tree_pct) > 2 ? 'var(--warn)' : 'inherit'}">${fmt.signed(m.lsm_vs_tree_pct, 2)}%</td>
      <td class="num">${fmt.num(m.pde, 2)} <span class="hint">vs ${fmt.num(m.tree_averaged, 1)} ± ${fmt.num(m.tree_averaged_sd, 1)}</span></td>
      <td class="num" style="color:${Math.abs(m.pde_vs_tree_pct) > 2 ? 'var(--warn)' : 'inherit'}">${fmt.signed(m.pde_vs_tree_pct, 2)}%</td>
      <td class="num">[${fmt.num(m.bracket_lower, 0)}, ${fmt.num(m.bracket_upper, 0)}] ${m.tree_inside_bracket ? '✓' : '✗'}</td>
    </tr>`).join('')}</tbody>
`;
  el('method-note').innerHTML = `A single fine tree is not a reference value: a double-obstacle
    lattice oscillates with the step count because the free boundary sits between nodes differently
    at every resolution. The tree it is compared against is averaged over eleven step counts from
    1,500 to 2,500, with its spread shown, which is the numerical uncertainty that actually remains.
    The out-of-the-money put at a 1% penalty is the hard case for every scheme &mdash; its free
    boundary sits on the payoff kink &mdash; and its disagreement is left visible.`;
}

function validation() {
  el('validation-list').innerHTML = G.checks.map((c) => `
    <div class="check"><span class="mark ${c.pass ? 'ok' : 'no'}">${c.pass ? '✓' : '✗'}</span>
      <span><strong>${h(c.name)}</strong><br><span class="detail">${h(c.detail)}</span></span></div>`).join('');
}

function priceTable() {
  const pens = [...new Set(G.price_table.map((r) => r.penalty_pct))];
  el('table-controls').innerHTML = `<div class="ctl"><label>Show</label><div class="segmented" id="pt-mode">
      <button data-m="price" aria-pressed="true">game value</button>
      <button data-m="cancellation_value" aria-pressed="false">cancellation right</button>
      <button data-m="american" aria-pressed="false">American value</button>
    </div></div>`;
  const draw = (mode) => {
    const strikes = [...new Set(G.price_table.map((r) => r.strike_pct))];
    const tenors = [...new Set(G.price_table.map((r) => r.tenor))];
    let html = `<thead><tr><th>Strike</th><th>Tenor</th>${pens.map((p) => `<th class="num">δ = ${fmt.pct(p, 0)}</th>`).join('')}</tr></thead><tbody>`;
    for (const k of strikes) {
      for (const t of tenors) {
        html += `<tr><td>${fmt.pct(k, 0)} of spot</td><td>${t < 1 ? `${t * 12} m` : `${t} y`}</td>`;
        for (const p of pens) {
          const row = G.price_table.find((r) => r.strike_pct === k && r.tenor === t && r.penalty_pct === p);
          html += `<td class="num">${row ? fmt.num(row[mode], 1) : '—'}</td>`;
        }
        html += '</tr>';
      }
    }
    html += `</tbody><caption>${st.kind === 'put' ? 'Put' : 'Call'} on the NIFTY 50 at
      ${fmt.num(G.inputs.s0, 2)}, σ = ${fmt.pct(G.inputs.sigma, 2)}, r = ${fmt.pct(G.inputs.r, 2)},
      q = ${fmt.pct(G.inputs.q, 2)}; index points, 1,200-step tree.</caption>`;
    el('price-table').innerHTML = html;
  };
  draw('price');
  el('pt-mode').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
    el('pt-mode').querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    draw(b.dataset.m);
  }));
}

export function renderGame(data) {
  G = data;
  inputsCard();
  controls();
  penaltyChart();
  volChart();
  convergenceChart();
  methodTable();
  validation();
  priceTable();
}

export function heroGameTiles(data) {
  const a = data.atm_finding;
  return [
    tile('Israeli put, at the money', fmt.num(a.price, 2),
      `= the penalty exactly, until δ &gt; ${fmt.num(a.threshold_pct * 100, 2)}% of spot`),
    tile('Cancellation right is worth', fmt.num(data.reference.cancellation_value, 1),
      `${fmt.pct(data.reference.cancellation_value / data.reference.american, 0)} of the American value`),
  ].join('');
}
