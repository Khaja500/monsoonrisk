/* The pricing engines, re-implemented in the browser so every control on the
   page re-prices for real instead of looking up a precomputed cell.

   They mirror src/b_bonds and src/c_game one-for-one:
     - catastrophe bonds: inverse-transform sampling off the fitted quantile
       grid exported by scripts/build_weather_data.py, or the historical
       seasons themselves for burn analysis;
     - the game option: the same CRR recursion V = min(H, max(G, C)).
   Reference values computed in Python are shown next to the live numbers so
   any disagreement is visible. */

/* ---------- normal distribution ---------- */
const A = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
  1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00];
const B = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
  6.680131188771972e+01, -1.328068155288572e+01];
const C = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
  -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00];
const D = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
  3.754408661907416e+00];

export function normPpf(p) {
  if (p <= 0) return -Infinity;
  if (p >= 1) return Infinity;
  const pl = 0.02425;
  if (p < pl) {
    const q = Math.sqrt(-2 * Math.log(p));
    return (((((C[0] * q + C[1]) * q + C[2]) * q + C[3]) * q + C[4]) * q + C[5])
      / ((((D[0] * q + D[1]) * q + D[2]) * q + D[3]) * q + 1);
  }
  if (p > 1 - pl) return -normPpf(1 - p);
  const q = p - 0.5, r = q * q;
  return (((((A[0] * r + A[1]) * r + A[2]) * r + A[3]) * r + A[4]) * r + A[5]) * q
    / (((((B[0] * r + B[1]) * r + B[2]) * r + B[3]) * r + B[4]) * r + 1);
}

export function normCdf(x) {
  // Abramowitz-Stegun 7.1.26 on the error function
  const s = x < 0 ? -1 : 1, z = Math.abs(x) / Math.SQRT2;
  const t = 1 / (1 + 0.3275911 * z);
  const erf = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-z * z);
  return 0.5 * (1 + s * erf);
}

/* ---------- deterministic RNG so the page is reproducible ---------- */
export function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/* ---------- inverse transform off the exported quantile grid ---------- */
export function gridPpf(grid, u) {
  const { q, x } = grid;
  if (u <= q[0]) return x[0];
  if (u >= q[q.length - 1]) return x[x.length - 1];
  let lo = 0, hi = q.length - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (q[mid] <= u) lo = mid; else hi = mid; }
  const w = (u - q[lo]) / (q[hi] - q[lo]);
  return x[lo] + w * (x[hi] - x[lo]);
}

export function gridSf(grid, value) {
  const { q, x } = grid;
  if (value <= x[0]) return 1;
  if (value >= x[x.length - 1]) return 0;
  let lo = 0, hi = x.length - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (x[mid] <= value) lo = mid; else hi = mid; }
  const w = (value - x[lo]) / (x[hi] - x[lo]);
  return 1 - (q[lo] + w * (q[hi] - q[lo]));
}

/* ---------- Wang transform weights for an ascending-sorted sample ---------- */
export function wangWeights(n, lam) {
  // lam = 0 is the physical measure; short-circuit it so the uniform weights
  // are exact rather than carrying the error of the normal-cdf approximation.
  if (lam === 0) return new Float64Array(n).fill(1 / n);
  const g = new Float64Array(n + 1);
  for (let i = 0; i <= n; i++) {
    const u = (n - i) / n;
    g[i] = i === 0 ? 1 : (i === n ? 0 : normCdf(normPpf(u) + lam));
  }
  const w = new Float64Array(n);
  let s = 0;
  for (let i = 0; i < n; i++) { w[i] = g[i] - g[i + 1]; s += w[i]; }
  for (let i = 0; i < n; i++) w[i] /= s;
  return w;
}

/* ---------- Module B: principal-at-risk bond ---------- */
export function priceCatBond(opts) {
  const {
    attach, exhaust, tenor, inverted = false, grid = null, sample = null,
    rule = 'wang', m = 1.5, lam = 0.25, beta = 0.5,
    rate = 0.056, collateral = 0.056, nPaths = 20000, seed = 20261013, method = 'mc',
  } = opts;
  const FACE = 100;
  const rng = mulberry32(seed);
  const paths = method === 'burn' && sample
    ? (tenor === 1 ? sample.map((v) => [v])
      : Array.from({ length: nPaths }, () => Array.from({ length: tenor },
        () => sample[Math.floor(rng() * sample.length)])))
    : Array.from({ length: Math.max(nPaths / 2 | 0, 1) }, () => {
      const us = Array.from({ length: tenor }, () => rng());
      return [us.map((u) => gridPpf(grid, u)), us.map((u) => gridPpf(grid, 1 - u))];
    }).flat();

  const span = inverted ? attach - exhaust : exhaust - attach;
  const lossFrac = (x) => {
    if (span === 0) return (inverted ? x <= attach : x >= attach) ? 1 : 0;
    const raw = inverted ? (attach - x) / span : (x - attach) / span;
    return Math.max(0, Math.min(1, raw));
  };
  const df = Array.from({ length: tenor }, (_, t) => Math.exp(-rate * (t + 1)));

  const n = paths.length;
  const pvLoss = new Float64Array(n);
  const outstanding = Array.from({ length: n }, () => new Float64Array(tenor));
  const surviving = new Float64Array(n);
  let elSum = 0, elSq = 0;
  const totalLoss = new Float64Array(n);
  const yearLoss = Array.from({ length: tenor }, () => new Float64Array(n));

  for (let i = 0; i < n; i++) {
    let remaining = FACE, pv = 0;
    for (let t = 0; t < tenor; t++) {
      outstanding[i][t] = remaining;
      const applied = Math.min(remaining, lossFrac(paths[i][t]) * FACE);
      yearLoss[t][i] = applied;
      remaining -= applied;
      pv += applied * df[t];
    }
    surviving[i] = remaining;
    pvLoss[i] = pv;
    totalLoss[i] = FACE - remaining;
    elSum += totalLoss[i];
    elSq += totalLoss[i] * totalLoss[i];
  }

  // pricing-measure weights
  let weights;
  if (rule === 'wang') {
    const order = Array.from({ length: n }, (_, i) => i).sort((a, b) => pvLoss[a] - pvLoss[b]);
    const ws = wangWeights(n, lam);
    weights = new Float64Array(n);
    order.forEach((idx, k) => { weights[idx] = ws[k]; });
  } else {
    weights = new Float64Array(n).fill(1 / n);
  }

  const eqOut = new Float64Array(tenor);
  let eqSurv = 0;
  for (let i = 0; i < n; i++) {
    for (let t = 0; t < tenor; t++) eqOut[t] += weights[i] * outstanding[i][t];
    eqSurv += weights[i] * surviving[i];
  }
  let denom = 0;
  for (let t = 0; t < tenor; t++) denom += eqOut[t] * df[t];
  const parSpread = denom ? (FACE - eqSurv * df[tenor - 1] - collateral * denom) / denom : 0;

  let elAnnual = 0, sdAnnual = 0;
  for (let t = 0; t < tenor; t++) {
    const col = yearLoss[t];
    let mean = 0; for (let i = 0; i < n; i++) mean += col[i]; mean /= n;
    let v = 0; for (let i = 0; i < n; i++) v += (col[i] - mean) ** 2; v /= (n - 1);
    elAnnual += mean / tenor; sdAnnual += Math.sqrt(v) / tenor;
  }
  elAnnual /= 100; sdAnnual /= 100;

  const fairSpread = rule === 'r1' ? m * elAnnual
    : rule === 'sd' ? elAnnual + beta * sdAnnual
      : parSpread;

  let price = 0;
  for (let i = 0; i < n; i++) {
    let pv = 0;
    for (let t = 0; t < tenor; t++) pv += (collateral + fairSpread) * outstanding[i][t] * df[t];
    price += weights[i] * (pv + surviving[i] * df[tenor - 1]);
  }

  const firstYear = paths.map((p) => p[0]);
  const hit = (lvl) => firstYear.reduce((acc, x) => acc + ((inverted ? x <= lvl : x >= lvl) ? 1 : 0), 0) / n;
  const sorted = Array.from(totalLoss).sort((a, b) => a - b);
  const quant = (p) => sorted[Math.min(sorted.length - 1, Math.floor(p * (sorted.length - 1)))];
  const cvar = (p) => { const c = quant(p); const tail = sorted.filter((v) => v >= c); return tail.length ? tail.reduce((a, b) => a + b, 0) / tail.length : c; };
  const maxLoss = FACE;
  const exceedance = Array.from({ length: 41 }, (_, k) => {
    const x = (k / 40) * maxLoss;
    return { loss: x, prob: sorted.reduce((acc, v) => acc + (v > x ? 1 : 0), 0) / n };
  });

  return {
    nPaths: n, method, elAnnual, sdAnnual, fairSpread, parSpread, price,
    probAttach: hit(attach), probExhaust: hit(exhaust),
    elTotal: elSum / n / 100, var95: quant(0.95), var99: quant(0.99),
    cvar95: cvar(0.95), cvar99: cvar(0.99), exceedance,
    expectedLossSe: Math.sqrt(Math.max(elSq / n - (elSum / n) ** 2, 0) / n) / 100,
  };
}

/* ---------- Module B3: the CDR index future ---------- */
export function cdrFairValue({ spot, remainingNormal, remainingSd, factor = 1, lambda = 0, trend = 0 }) {
  const forecast = (factor - 1) * remainingNormal;
  const premium = lambda * remainingSd;
  return { spot, forecast, trend, premium, fair: spot + forecast + trend + premium };
}

/* ---------- Module C: CRR tree for the game option ---------- */
export function crrGame({ s0, strike, r, q, sigma, maturity, steps = 600, kind = 'put',
  penalty = 0, style = 'game', collect = false }) {
  const dt = maturity / steps;
  const u = Math.exp(sigma * Math.sqrt(dt));
  const d = 1 / u;
  const p = (Math.exp((r - q) * dt) - d) / (u - d);
  const disc = Math.exp(-r * dt);
  if (!(p > 0 && p < 1)) return { price: NaN, error: 'tree probability outside (0,1)' };

  const pay = (s) => kind === 'put' ? Math.max(strike - s, 0) : Math.max(s - strike, 0);
  let spot = new Float64Array(steps + 1);
  let v = new Float64Array(steps + 1);
  for (let j = 0; j <= steps; j++) {
    spot[j] = s0 * Math.pow(u, steps - j) * Math.pow(d, j);
    v[j] = pay(spot[j]);
  }
  const exBoundary = [], caBand = [];
  for (let i = steps - 1; i >= 0; i--) {
    const nv = new Float64Array(i + 1);
    const ns = new Float64Array(i + 1);
    let exMax = null, caLo = null, caHi = null;
    for (let j = 0; j <= i; j++) {
      const cont = disc * (p * v[j] + (1 - p) * v[j + 1]);
      ns[j] = spot[j] / u;
      const g = pay(ns[j]);
      if (style === 'european') { nv[j] = cont; continue; }
      const hold = Math.max(g, cont);
      nv[j] = style === 'american' ? hold : Math.min(g + penalty, hold);
      if (collect && style === 'game') {
        if (g >= cont - 1e-12 && g > 0) exMax = exMax === null ? ns[j] : Math.max(exMax, ns[j]);
        if (cont > g + penalty + 1e-12) {
          caLo = caLo === null ? ns[j] : Math.min(caLo, ns[j]);
          caHi = caHi === null ? ns[j] : Math.max(caHi, ns[j]);
        }
      }
    }
    if (collect && style === 'game') {
      exBoundary.push({ t: i * dt, boundary: exMax });
      caBand.push({ t: i * dt, lo: caLo, hi: caHi });
    }
    v = nv; spot = ns;
  }
  return {
    price: v[0],
    exerciseBoundary: exBoundary.reverse(),
    cancellationBand: caBand.reverse(),
  };
}

export function gameBundle(args) {
  const game = crrGame({ ...args, style: 'game', collect: true });
  const american = crrGame({ ...args, penalty: 0, style: 'american' }).price;
  const european = crrGame({ ...args, penalty: 0, style: 'european' }).price;
  const intrinsic = args.kind === 'put' ? Math.max(args.strike - args.s0, 0) : Math.max(args.s0 - args.strike, 0);
  const bump = 0.01 * args.s0;
  const coarse = Math.max(200, Math.floor((args.steps || 600) / 2));
  const at = (over) => crrGame({ ...args, ...over, steps: coarse, style: 'game', collect: false }).price;
  const up = at({ s0: args.s0 + bump }), dn = at({ s0: args.s0 - bump }), mid = at({});
  return {
    ...game, american, european, intrinsic,
    cancellationValue: american - game.price,
    greeks: {
      delta: (up - dn) / (2 * bump),
      gamma: (up - 2 * mid + dn) / (bump * bump),
      vega: (at({ sigma: args.sigma + 0.01 }) - at({ sigma: Math.max(args.sigma - 0.01, 1e-4) })) / 2,
      rho: (at({ r: args.r + 0.01 }) - at({ r: args.r - 0.01 })) / 2,
      theta: at({ maturity: Math.max(args.maturity - 1 / 365, 1e-4) }) - mid,
    },
    checks: {
      'V >= intrinsic': game.price >= intrinsic - 1e-6,
      'V <= American': game.price <= american + 1e-6,
      'V <= intrinsic + penalty': game.price <= intrinsic + args.penalty + 1e-6,
      'American >= European': american >= european - 1e-6,
    },
  };
}
