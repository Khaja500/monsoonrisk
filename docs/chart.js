/* Small SVG chart helpers: line, area band, bars, dumbbells, histogram.
   Everything is drawn from CSS variables so light and dark are one definition,
   and every plot gets a crosshair tooltip. */

export const fmt = {
  mm: (v, d = 0) => `${v.toLocaleString('en-IN', { maximumFractionDigits: d, minimumFractionDigits: d })} mm`,
  num: (v, d = 2) => Number(v).toLocaleString('en-IN', { maximumFractionDigits: d, minimumFractionDigits: d }),
  int: (v) => Math.round(v).toLocaleString('en-IN'),
  inr: (v, d = 0) => `₹${Math.abs(v) >= 1e5
    ? (v / 1e5).toLocaleString('en-IN', { maximumFractionDigits: 2 }) + ' lakh'
    : v.toLocaleString('en-IN', { maximumFractionDigits: d })}`,
  pct: (v, d = 1) => `${(v * 100).toLocaleString('en-IN', { maximumFractionDigits: d, minimumFractionDigits: d })}%`,
  signed: (v, d = 1) => (v >= 0 ? '+' : '−') + Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: d, minimumFractionDigits: d }),
};

const NS = 'http://www.w3.org/2000/svg';
const el = (name, attrs = {}, parent = null) => {
  const node = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) node.setAttribute(k, v);
  if (parent) parent.appendChild(node);
  return node;
};

function niceTicks(lo, hi, count = 5) {
  if (!isFinite(lo) || !isFinite(hi) || lo === hi) return [lo];
  const span = hi - lo;
  const raw = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm >= 7.5 ? 10 : norm >= 3.5 ? 5 : norm >= 1.5 ? 2 : 1) * mag;
  const out = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi + step * 1e-9; t += step) out.push(+t.toFixed(10));
  return out;
}

/* A plot frame: scales, grid, axes, hover plumbing. */
export function frame(host, opts = {}) {
  const {
    height = 260, padLeft = 56, padRight = 18, padTop = 24, padBottom = 34,
    xDomain, yDomain, xTicks, yTicks, xFormat = (v) => v, yFormat = fmt.int,
    yLabel = null, xLabel = null, width = 760, xTickCount = 6, yTickCount = 5,
  } = opts;
  host.innerHTML = '';
  host.classList.add('chart');
  const svg = el('svg', { viewBox: `0 0 ${width} ${height}`, role: 'img', preserveAspectRatio: 'none' }, host);
  const [x0, x1] = xDomain, [y0, y1] = yDomain;
  const sx = (v) => padLeft + ((v - x0) / (x1 - x0 || 1)) * (width - padLeft - padRight);
  const sy = (v) => height - padBottom - ((v - y0) / (y1 - y0 || 1)) * (height - padTop - padBottom);

  const gGrid = el('g', { class: 'axis' }, svg);
  const yt = yTicks || niceTicks(y0, y1, yTickCount);
  for (const t of yt) {
    const y = sy(t);
    el('line', { class: 'gridline', x1: padLeft, x2: width - padRight, y1: y, y2: y }, gGrid);
    el('text', { x: padLeft - 8, y: y + 3.5, 'text-anchor': 'end' }, gGrid).textContent = yFormat(t);
  }
  const xt = xTicks || niceTicks(x0, x1, xTickCount);
  for (const t of xt) {
    const x = sx(t);
    el('text', { x, y: height - padBottom + 16, 'text-anchor': 'middle' }, gGrid).textContent = xFormat(t);
  }
  el('line', { x1: padLeft, x2: width - padRight, y1: sy(y0), y2: sy(y0), stroke: 'var(--border-strong)' }, gGrid);
  if (yLabel) el('text', { x: 2, y: 11, class: 'series-label', fill: 'var(--text-muted)' }, gGrid).textContent = yLabel;
  if (xLabel) el('text', { x: width - padRight, y: height - 2, 'text-anchor': 'end', class: 'series-label', fill: 'var(--text-muted)' }, gGrid).textContent = xLabel;

  const plot = el('g', {}, svg);
  const overlay = el('g', {}, svg);
  const tip = document.createElement('div');
  tip.className = 'tooltip';
  host.appendChild(tip);

  const api = {
    svg, plot, overlay, sx, sy, width, height, padLeft, padRight, padTop, padBottom,
    xDomain, yDomain, el: (n, a, p) => el(n, a, p || plot),
    line(points, { color = 'var(--series-1)', dash = null, w = 2, opacity = 1, label = null } = {}) {
      const d = points.filter((p) => isFinite(p[1])).map((p, i) => `${i ? 'L' : 'M'}${sx(p[0]).toFixed(2)} ${sy(p[1]).toFixed(2)}`).join('');
      el('path', { d, fill: 'none', stroke: color, 'stroke-width': w, 'stroke-dasharray': dash, 'stroke-linejoin': 'round', 'stroke-linecap': 'round', opacity }, plot);
      if (label) {
        const last = points.filter((p) => isFinite(p[1])).at(-1);
        el('text', { x: sx(last[0]) + 5, y: sy(last[1]) + 4, class: 'series-label', fill: color }, plot).textContent = label;
      }
    },
    band(points, { color = 'var(--series-1)', opacity = 0.14 } = {}) {
      const up = points.map((p, i) => `${i ? 'L' : 'M'}${sx(p[0]).toFixed(2)} ${sy(p[1]).toFixed(2)}`).join('');
      const dn = points.slice().reverse().map((p) => `L${sx(p[0]).toFixed(2)} ${sy(p[2]).toFixed(2)}`).join('');
      el('path', { d: `${up}${dn}Z`, fill: color, opacity, stroke: 'none' }, plot);
    },
    hline(v, { color = 'var(--text-muted)', dash = '4 4', label = null, w = 1.5 } = {}) {
      const y = sy(v);
      el('line', { x1: padLeft, x2: width - padRight, y1: y, y2: y, stroke: color, 'stroke-width': w, 'stroke-dasharray': dash }, plot);
      if (label) {
        const t = el('text', { x: padLeft + 6, y: y - 5, class: 'series-label', fill: color }, plot);
        t.textContent = label;
      }
    },
    vline(v, { color = 'var(--text-muted)', dash = '4 4', label = null } = {}) {
      const x = sx(v);
      el('line', { x1: x, x2: x, y1: padTop, y2: height - padBottom, stroke: color, 'stroke-width': 1.5, 'stroke-dasharray': dash }, plot);
      if (label) el('text', { x: x + 4, y: padTop + 10, class: 'series-label', fill: color }, plot).textContent = label;
    },
    dot(x, y, { color = 'var(--series-1)', r = 4.5, ring = true } = {}) {
      el('circle', { cx: sx(x), cy: sy(y), r, fill: color, stroke: ring ? 'var(--surface-1)' : 'none', 'stroke-width': 2 }, plot);
    },
    hover(items, render) {
      // items: [{x, y, payload}] in data space; render(payload) -> html
      const hit = el('rect', { x: padLeft, y: padTop, width: width - padLeft - padRight, height: height - padTop - padBottom, fill: 'transparent' }, overlay);
      const cross = el('line', { x1: 0, x2: 0, y1: padTop, y2: height - padBottom, stroke: 'var(--border-strong)', 'stroke-width': 1, opacity: 0 }, overlay);
      const mark = el('circle', { r: 5, fill: 'var(--text-primary)', opacity: 0, stroke: 'var(--surface-1)', 'stroke-width': 2 }, overlay);
      const move = (ev) => {
        const box = host.getBoundingClientRect();
        const px = ((ev.clientX - box.left) / box.width) * width;
        let best = null, bd = Infinity;
        for (const it of items) { const d = Math.abs(sx(it.x) - px); if (d < bd) { bd = d; best = it; } }
        if (!best) return;
        cross.setAttribute('x1', sx(best.x)); cross.setAttribute('x2', sx(best.x));
        cross.setAttribute('opacity', 1);
        mark.setAttribute('cx', sx(best.x)); mark.setAttribute('cy', sy(best.y));
        mark.setAttribute('opacity', isFinite(best.y) ? 1 : 0);
        tip.innerHTML = render(best.payload ?? best);
        tip.style.opacity = 1;
        const tx = Math.min(Math.max((sx(best.x) / width) * box.width - tip.offsetWidth / 2, 2), box.width - tip.offsetWidth - 2);
        tip.style.left = `${tx}px`;
        tip.style.top = `${Math.max((sy(best.y) / height) * box.height - tip.offsetHeight - 12, 0)}px`;
      };
      hit.addEventListener('pointermove', move);
      hit.addEventListener('pointerleave', () => { tip.style.opacity = 0; cross.setAttribute('opacity', 0); mark.setAttribute('opacity', 0); });
    },
  };
  return api;
}

export function legend(host, items) {
  host.innerHTML = items.map((i) => `<span class="item"><span class="swatch ${i.line ? 'line' : ''}" style="background:${i.color}${i.ring ? `;box-shadow:inset 0 0 0 2px ${i.ring}` : ''}${i.dash ? ';opacity:.75' : ''}"></span>${i.label}</span>`).join('');
}

/* Vertical bars with 4px rounded data-ends, anchored to the baseline. */
export function bars(host, rows, opts = {}) {
  const { yFormat = fmt.int, tipRender = null, color = 'var(--series-1)', height = 240, yMin = null } = opts;
  const vals = rows.map((r) => r.value);
  const lo = yMin !== null ? yMin : Math.min(0, ...vals);
  const hi = Math.max(...vals) * 1.08;
  const f = frame(host, {
    ...opts, height,
    xDomain: [-0.5, rows.length - 0.5], yDomain: [lo, hi],
    xTicks: rows.map((_, i) => i), xFormat: (i) => rows[i]?.label ?? '', yFormat,
  });
  const bw = Math.min(46, ((f.width - f.padLeft - f.padRight) / rows.length) * 0.62);
  rows.forEach((r, i) => {
    const y = f.sy(Math.max(r.value, lo));
    const y0 = f.sy(Math.max(lo, 0));
    f.el('rect', {
      x: f.sx(i) - bw / 2, y: Math.min(y, y0), width: bw, height: Math.abs(y0 - y) || 1,
      rx: 4, fill: r.color || color,
    });
  });
  f.hover(rows.map((r, i) => ({ x: i, y: r.value, payload: r })), tipRender || ((r) => `<b>${r.label}</b><br>${yFormat(r.value)}`));
  return f;
}
